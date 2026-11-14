"""
One client for both System One models.

Jev (TypeSafe, hosted) and CLM (open weights, served locally by `clm-serve`)
speak the SAME wire format:

    POST {base_url}/v1/systemone
    Authorization: Bearer <key>          (CLM: only if CLM_API_KEY is set)
    {"model": ..., "state": ..., "questions": {id: {"type": "choice"|"score"|"noul", ...}}}

    -> {"model": ..., "answers": {id: {"type": ..., ...}}, "usage": {...}}

So every demo sends byte-for-byte the same request to both models. That is what
makes the comparison fair: same state, same questions, same option texts.

Each call returns a normalized `Result` with a measured round-trip latency. A
failed call is reported as an error. It is never silently replaced by a random
answer (that would corrupt the comparison).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

try:  # optional: read a .env file if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


# ── question builders (same shapes as typesafe_sdk / clm) ─────────────────────

def choice(instructions: str, criteria: dict[str, str]) -> dict:
    """Pick exactly one option. `criteria` maps option key -> description."""
    return {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}


def score(instructions: str, levels: list[str]) -> dict:
    """Rate on an ordered scale (level 0 = lowest)."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul(instructions: str) -> dict:
    """Yes/no statement; the answer is the probability that it is true."""
    return {"type": "noul", "instructions": instructions}


# ── providers ─────────────────────────────────────────────────────────────────

@dataclass
class Provider:
    name: str            # "jev" | "clm"
    label: str           # shown in the UI
    base_url: str
    model: str
    api_key: str | None
    timeout_s: float
    hosted_where: str    # explains network latency to the audience

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and (self.name != "jev" or bool(self.api_key))


def providers_from_env() -> dict[str, Provider]:
    return {
        "jev": Provider(
            name="jev",
            label="Jev (TypeSafe)",
            base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/"),
            model=os.getenv("TYPESAFE_MODEL", "jev-latest"),
            # TYPESAFE_API_KEY is the official name; JEV_API_KEY kept for the old scripts
            api_key=os.getenv("TYPESAFE_API_KEY") or os.getenv("JEV_API_KEY") or None,
            timeout_s=float(os.getenv("TYPESAFE_TIMEOUT", "30")),
            hosted_where="hosted API (US West Coast), so times include the internet round trip",
        ),
        "clm": Provider(
            name="clm",
            label="CLM-8B (open weights)",
            base_url=os.getenv("CLM_BASE_URL", "http://127.0.0.1:8700").rstrip("/"),
            model=os.getenv("CLM_MODEL", "clm-latest"),
            api_key=os.getenv("CLM_API_KEY") or None,
            timeout_s=float(os.getenv("CLM_TIMEOUT", "60")),
            hosted_where="runs on your own GPU via clm-serve",
        ),
    }


# Which models each demo uses. Scam check and Beat the guard use CLM only by
# default; set e.g. SCAM_MODELS=jev,clm in .env to compare both again.
DEMO_DEFAULT_MODELS = {"scam": ["clm"], "guard": ["clm"]}


def demo_models(demo: str) -> list[str]:
    """Models a demo asks, from <DEMO>_MODELS (comma-separated) or the default above."""
    raw = os.getenv(f"{demo.upper()}_MODELS", "")
    chosen = [m.strip().lower() for m in raw.split(",") if m.strip()]
    valid = [m for m in chosen if m in ("jev", "clm")]
    return list(dict.fromkeys(valid)) or list(DEMO_DEFAULT_MODELS.get(demo, ["jev", "clm"]))


# ── results ───────────────────────────────────────────────────────────────────

@dataclass
class Answer:
    type: str
    value: Any                   # choice key | expected score level (float) | P(true)
    label: str                   # discrete answer: choice key, score level, "true"/"false"
    probabilities: dict[str, float]
    confidence: float            # Jev/CLM confidence; for noul: |p - 0.5| * 2


@dataclass
class Result:
    provider: str
    ok: bool
    answers: dict[str, Answer] = field(default_factory=dict)
    latency_ms: float = 0.0          # measured round trip, what a user would feel
    server_ms: float | None = None   # model time reported by the server (CLM only)
    model: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize(a: dict) -> Answer:
    t = a.get("type")
    if t == "noul":
        p = float(a["noul"])
        return Answer("noul", p, "true" if p >= 0.5 else "false",
                      {"true": p, "false": 1.0 - p}, abs(p - 0.5) * 2)
    if t == "choice":
        probs = {k: float(v) for k, v in a.get("probabilities", {}).items()}
        return Answer("choice", a["choice"], a["choice"], probs, float(a.get("confidence", 0.0)))
    if t == "score":
        probs = {str(k): float(v) for k, v in a.get("probabilities", {}).items()}
        label = max(probs, key=probs.get) if probs else str(round(float(a["score"])))
        return Answer("score", float(a["score"]), label, probs, float(a.get("confidence", 0.0)))
    raise ValueError(f"unknown answer type {t!r}")


def _validate(questions: dict[str, dict], answers: dict[str, Answer]) -> str | None:
    """Defensive check that the answer is one of the options we offered."""
    for qid, q in questions.items():
        a = answers.get(qid)
        if a is None:
            return f"missing answer for {qid!r}"
        if q["type"] == "choice" and a.value not in q["criteria"]:
            return f"{qid!r}: answer {a.value!r} is not one of the options"
    return None


# ── client ────────────────────────────────────────────────────────────────────

class SystemOneClient:
    """Async client. Use `ask()` for one model or `compare()` to query all models in parallel."""

    def __init__(self, providers: dict[str, Provider] | None = None):
        self.providers = providers or providers_from_env()
        self._http = httpx.AsyncClient()

    async def aclose(self):
        await self._http.aclose()

    async def ask(self, provider: str, state: Any, questions: dict[str, dict]) -> Result:
        p = self.providers[provider]
        if not p.configured:
            return Result(provider, False, error="not configured (set TYPESAFE_API_KEY in .env)"
                          if provider == "jev" else "not configured")
        headers = {"Content-Type": "application/json"}
        if p.api_key:
            headers["Authorization"] = f"Bearer {p.api_key}"
        body = {"model": p.model, "state": state, "questions": questions}
        t0 = time.perf_counter()
        try:
            r = await self._http.post(f"{p.base_url}/v1/systemone", json=body,
                                      headers=headers, timeout=p.timeout_s)
            latency = (time.perf_counter() - t0) * 1000
            if r.status_code != 200:
                return Result(provider, False, latency_ms=latency,
                              error=f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            answers = {k: _normalize(v) for k, v in data["answers"].items()}
            problem = _validate(questions, answers)
            server_ms = r.headers.get("X-CLM-Latency-Ms")
            return Result(provider, problem is None, answers, latency,
                          float(server_ms) if server_ms else None, data.get("model"), problem)
        except httpx.ConnectError:
            return Result(provider, False, latency_ms=(time.perf_counter() - t0) * 1000,
                          error=f"cannot reach {p.base_url} (is it running?)")
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            return Result(provider, False, latency_ms=(time.perf_counter() - t0) * 1000,
                          error=f"{type(exc).__name__}: {exc}")

    async def compare(self, state: Any, questions: dict[str, dict],
                      providers: list[str] | None = None) -> dict[str, Result]:
        """Send the identical request to every provider at the same time."""
        names = providers or list(self.providers)
        results = await asyncio.gather(*(self.ask(n, state, questions) for n in names))
        return dict(zip(names, results))

    async def ping(self, provider: str, n: int = 5) -> dict:
        """Network round trip to the provider WITHOUT model work (median of n small GETs).

        CLM: GET /health. Jev: GET on the API root (any HTTP status counts, we only time it).
        Recorded with every session so the audience can see how much of a model's time
        is just the network.
        """
        p = self.providers[provider]
        url = f"{p.base_url}/health" if provider == "clm" else f"{p.base_url}/"
        samples = []
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                await self._http.get(url, timeout=5)
            except Exception:  # noqa: BLE001
                return {"url": url, "samples_ms": samples, "median_ms": None, "error": "unreachable"}
            samples.append(round((time.perf_counter() - t0) * 1000, 1))
        samples_sorted = sorted(samples)
        return {"url": url, "samples_ms": samples, "median_ms": samples_sorted[len(samples) // 2]}

    async def health(self) -> dict[str, dict]:
        out = {}
        for name, p in self.providers.items():
            info = {"label": p.label, "configured": p.configured, "where": p.hosted_where,
                    "base_url": p.base_url, "model": p.model, "reachable": None}
            if name == "clm" and p.configured:
                try:
                    r = await self._http.get(f"{p.base_url}/health", timeout=3)
                    info["reachable"] = r.status_code == 200
                except Exception:  # noqa: BLE001
                    info["reachable"] = False
            out[name] = info
        return out


def ask_sync(provider: str, state: Any, questions: dict[str, dict]) -> Result:
    """Blocking helper for scripts."""
    async def _run():
        c = SystemOneClient()
        try:
            return await c.ask(provider, state, questions)
        finally:
            await c.aclose()
    return asyncio.run(_run())
