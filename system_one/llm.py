"""
A plain chat LLM (System 2) for comparison: BHT's LUMIS API, model bht/medium by default.

Used by the Beat the Guard bot (Vaulty) and as an optional Rubik's cube player.
OpenAI-compatible, configured from environment variables:

    BHT_LLM_INF_API_KEY   the API key (read from your environment; keep it out of .env)
    LLM_BASE_URL          fixed endpoint. If unset, two are tried and the first that
                          answers is kept: inside the BHT cluster the internal
                          http://envoy-internal.envoy.svc.cluster.local/v1, otherwise
                          (and as fallback) the public https://lumis-api.bht-berlin.de/v1
    LLM_MODEL             default bht/medium   (context 32768, output up to 4096 tokens)
    LLM_API_KEY           optional, overrides BHT_LLM_INF_API_KEY
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import httpx

DEFAULT_BASE_URL = "https://lumis-api.bht-berlin.de/v1"
CLUSTER_BASE_URL = "http://envoy-internal.envoy.svc.cluster.local/v1"


def default_base_urls() -> list[str]:
    """Inside a Kubernetes pod the internal route comes first; on a laptop the public URL."""
    in_cluster = bool(os.getenv("KUBERNETES_SERVICE_HOST"))
    return [CLUSTER_BASE_URL, DEFAULT_BASE_URL] if in_cluster else [DEFAULT_BASE_URL, CLUSTER_BASE_URL]
DEFAULT_MODEL = "bht/medium"
_THINK = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)


@dataclass
class ChatResult:
    ok: bool
    text: str
    latency_ms: float
    model: str
    error: str | None = None


class ChatLLM:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 timeout: float = 90):
        fixed = base_url or os.getenv("LLM_BASE_URL")
        self.base_urls = [fixed.rstrip("/")] if fixed else default_base_urls()
        self.base_url = self.base_urls[0]
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("BHT_LLM_INF_API_KEY") or ""
        self._http = httpx.AsyncClient(timeout=timeout)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def label(self) -> str:
        return self.model

    async def aclose(self):
        await self._http.aclose()

    async def chat(self, messages: list[dict], max_tokens: int = 400, temperature: float = 0.7) -> ChatResult:
        t0 = time.perf_counter()
        if not self.configured:
            return ChatResult(False, "", 0.0, self.model,
                              "no API key: set BHT_LLM_INF_API_KEY in your environment (not in .env)")
        err = "no endpoint"
        # the endpoint that worked last time first; on a connection error try the next one
        for url in [self.base_url] + [u for u in self.base_urls if u != self.base_url]:
            try:
                r = await self._http.post(
                    f"{url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "messages": messages, "max_tokens": max_tokens,
                          "temperature": temperature})
                r.raise_for_status()
                self.base_url = url
                msg = r.json()["choices"][0]["message"]
                text = _THINK.sub("", msg.get("content") or "").strip()   # drop reasoning, keep the answer
                return ChatResult(True, text, (time.perf_counter() - t0) * 1000, self.model)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                err = f"cannot reach {url} ({type(exc).__name__})"
                continue
            except httpx.HTTPStatusError as exc:
                err = f"HTTP {exc.response.status_code} from {url}: {exc.response.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
            break
        return ChatResult(False, "", (time.perf_counter() - t0) * 1000, self.model, err)
