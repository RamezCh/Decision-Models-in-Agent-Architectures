"""
Behind the scenes of one model call: what was sent, what CLM actually reads, what came back.

CLM never sees our JSON. It turns the state into plain text (`key: value` lines), appends the
question after a blank line, and compares that with one text per possible answer. The two
functions below mirror contrastive-lm 0.1.0 (clm/schema.py: to_text, state_text, candidates),
so the web page can show exactly the texts that were compared.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def to_text(x: Any, indent: int = 0) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return str(x)
    pad = " " * indent
    if isinstance(x, dict):
        parts = [f"{pad}{k}:\n{to_text(v, indent + 2)}" if isinstance(v, (dict, list)) and v
                 else f"{pad}{k}: {to_text(v)}" for k, v in x.items()]
        return ("\n\n" if indent == 0 else "\n").join(parts)
    if isinstance(x, (list, tuple)):
        return "\n".join(f"{pad}-\n{to_text(v, indent + 2)}" if isinstance(v, (dict, list)) and v
                         else f"{pad}- {to_text(v)}" for v in x)
    return json.dumps(x, ensure_ascii=False)


def candidates(q: dict) -> dict[str, str]:
    """Option key -> the text CLM embeds for it."""
    t, crit, ins = q.get("type"), q.get("criteria"), to_text(q.get("instructions")).strip()
    if t == "choice":
        return {k: (to_text(v) if v not in (None, "") else k) for k, v in (crit or {}).items()}
    if t == "score":
        return {str(i): to_text(c) for i, c in enumerate(crit or [])}
    crit = crit if isinstance(crit, dict) else {}
    out = {}
    for k in ("false", "true"):
        d = crit.get(k)
        if d in (None, ""):
            d = (f"Yes. This is true: {ins}" if k == "true" else f"No. This is false: {ins}") if ins else k
        out[k] = f"{k}: {to_text(d)}"
    return out


def clm_reads(state: Any, questions: dict) -> dict:
    """{"context": state as text, "questions": {qid: {"instructions", "candidates"}}}."""
    return {"context": to_text(state).strip(),
            "questions": {qid: {"instructions": to_text(q.get("instructions")).strip(),
                                "type": q.get("type"), "candidates": candidates(q)}
                          for qid, q in questions.items()}}


def _plain(answers: dict) -> dict:
    return {k: (asdict(v) if is_dataclass(v) else v) for k, v in (answers or {}).items()}


def exchange(provider: str, state: Any, questions: dict, answers: dict | None, latency_ms=None,
             server_ms=None, model=None, error=None) -> dict:
    """One call, ready for the page's "behind the scenes" panel."""
    return {
        "provider": provider,
        "request": {"model": model, "state": state, "questions": questions},
        "reads": clm_reads(state, questions) if provider == "clm" else None,
        "response": {"model": model, "answers": _plain(answers), "latency_ms": latency_ms,
                     "server_ms": server_ms, "error": error},
    }


def exchange_from_call(call: dict) -> dict | None:
    """Same, from a recorded call (recordings store the request and the answers)."""
    req = call.get("request") or {}
    if "state" not in req or "questions" not in req:
        return None
    return exchange(call.get("provider", ""), req["state"], req["questions"], call.get("answers"),
                    call.get("latency_ms"), call.get("server_ms"), call.get("model"), call.get("error"))
