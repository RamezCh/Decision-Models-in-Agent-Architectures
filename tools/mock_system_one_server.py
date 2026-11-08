"""
Mock System One server, for rehearsing the UI without a GPU or a Jev key.

It speaks the same wire format as Jev and clm-serve (POST /v1/systemone), but its
"intelligence" is a few keyword rules plus noise. Every response says
model="mock-<name>", and the web app shows that name, so a mock can't be
mistaken for the real thing.

    python tools/mock_system_one_server.py --port 8700 --name clm --latency-ms 40
    python tools/mock_system_one_server.py --port 8701 --name jev --latency-ms 120

then in .env:
    CLM_BASE_URL=http://127.0.0.1:8700
    TYPESAFE_BASE_URL=http://127.0.0.1:8701
    TYPESAFE_API_KEY=mock
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import re
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# instruction keyword -> regex of state cues that make the statement "true"
CUES = [
    (r"money .*before", r"before (i|we) show|transfer|deposit .*(now|first|guarantee)|reservation fee|send .*eur|pay(ment)? .*before"),
    (r"cannot show", r"abroad|nigeria|spain|london|italy|dubai|canada|oil platform|cannot show|can't meet|not possible|impossible|quarantine|lisbon"),
    (r"keys by post|trustee", r"dhl|ups|courier|post you the keys|ship you|trustee|treuhand|protection|escrow|immoprotect|secure rent"),
    (r"whatsapp", r"whatsapp|western union|gift card|bitcoin|private email|gmail|friends & family"),
    (r"far below", r"\b(250|300|350|420|480|510|550|560|620|650|690|700|790|900)\b"),
    (r"passport|bank details", r"passport|iban|bank details|payslips|id card|schufa to my"),
    (r"pressures", r"today|immediately|fast decision|tomorrow|many people|20 other"),
    (r"emotional", r"inherited|late mother|god bless|pastor|husband left|emotional|missionary"),
    (r"vague", r"photos show everything|very good condition|charming"),
    (r"is a scam", r"western union|keys by|dhl|trustee|whatsapp|abroad|bitcoin|protection"),
    (r"trying to get a secret", r"password|secret|ignore|pretend|spell|backward|revers|hint|admin|developer|translat|base64|grandma|story"),
    (r"reveals the secret", r"__LEAK__"),
]


def _noise(seed: str) -> float:
    return int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) / 0xFFFFFF


def state_text(state) -> str:
    return state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)


def leak_in(state) -> bool:
    if not isinstance(state, dict):
        return False
    secret = str(next((v for k, v in state.items() if "Secret" in k), "")).upper()
    reply = str(next((v for k, v in state.items() if "reply" in k.lower()), "")).upper()
    letters = re.sub(r"[^A-Z]", "", reply)
    return bool(secret) and (secret in letters or secret[::-1] in letters or "NUT" in reply or "PISTAZIE" in reply)


def answer_noul(state, q, name) -> dict:
    text, ins = state_text(state).lower(), q.get("instructions", "").lower()
    hits = 0
    for key, rx in CUES:
        if re.search(key, ins):
            hits = 3 if rx == "__LEAK__" and leak_in(state) else len(re.findall(rx, text))
            break
    p = 1 / (1 + math.exp(-(2.2 * hits - 2.0 + (_noise(name + text + ins) - 0.5) * 2)))
    return {"type": "noul", "noul": round(p, 4)}


def _softmax(xs):
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    return [v / sum(e) for v in e]


def answer_choice(state, q, name) -> dict:
    text = state_text(state).lower()
    keys = list(q["criteria"])
    logits = []
    for k in keys:
        words = set(re.findall(r"[a-z]{4,}", str(q["criteria"][k]).lower()))
        logits.append(sum(w in text for w in words) * 0.6 + _noise(name + text + k) * 1.5)
    probs = _softmax(logits)
    j = max(range(len(keys)), key=probs.__getitem__)
    rest = [p for i, p in enumerate(probs) if i != j]
    conf = max(0.0, probs[j] - (sum(rest) / len(rest) if rest else 0))
    return {"type": "choice", "choice": keys[j], "confidence": round(conf, 4),
            "probabilities": {k: round(p, 4) for k, p in zip(keys, probs)}}


def answer_score(state, q, name) -> dict:
    n = len(q["criteria"])
    probs = _softmax([_noise(name + state_text(state) + str(i)) * 2 for i in range(n)])
    return {"type": "score", "score": sum(i * p for i, p in enumerate(probs)), "confidence": 0.3,
            "legend": {str(i): c for i, c in enumerate(q["criteria"])},
            "probabilities": {str(i): p for i, p in enumerate(probs)}}


def create_app(name: str, latency_ms: float) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True, "mock": True}

    @app.post("/v1/systemone")
    async def systemone(request: Request):
        t0 = time.perf_counter()
        body = await request.json()
        await asyncio.sleep(max(0.0, random.gauss(latency_ms, latency_ms * 0.15)) / 1000)
        fn = {"noul": answer_noul, "choice": answer_choice, "score": answer_score}
        answers = {k: fn[q["type"]](body["state"], q, name) for k, q in body["questions"].items()}
        return JSONResponse({"model": f"mock-{name}", "answers": answers, "usage": {"billing_units": len(answers)}},
                            headers={"X-CLM-Latency-Ms": f"{(time.perf_counter() - t0) * 1000:.1f}"}
                            if name == "clm" else None)

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--name", default="clm")
    ap.add_argument("--latency-ms", type=float, default=50)
    a = ap.parse_args()
    uvicorn.run(create_app(a.name, a.latency_ms), host="127.0.0.1", port=a.port, log_level="warning")
