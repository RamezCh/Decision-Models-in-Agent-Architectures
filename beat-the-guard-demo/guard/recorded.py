"""
Replay recorded guard verdicts (written by beat-the-guard-demo/record.py).

The recorded data are the raw probabilities and timings. The threshold and the
active defender are applied at replay time with the same build_verdicts() as the
live game, so moving the slider during a replay is honest: it re-decides on the
recorded probabilities, it doesn't invent new ones.
"""

from __future__ import annotations

from system_one.recordings import load_sessions, session_meta

from .game import DEFENDERS, build_verdicts, outcome_for


def _latest() -> dict[str, dict[str, dict]]:
    """{provider: {attack_id: {"input": call, "output": call, "meta": session_meta}}}"""
    out: dict[str, dict[str, dict]] = {}
    for session in load_sessions("guard"):
        meta = session_meta(session)
        pairs: dict[str, dict] = {}
        for call in session["calls"]:
            ctx = call.get("context", {})
            pairs.setdefault(ctx.get("attack_id"), {})[ctx.get("check")] = call
        for aid, pair in pairs.items():
            if "input" in pair and "output" in pair:
                ok = pair["input"].get("ok") and pair["output"].get("ok")
                slot = out.setdefault(session["header"]["provider"], {})
                if ok or aid not in slot:
                    slot[aid] = {**pair, "meta": meta}
    return out


def _view(pair: dict) -> dict:
    i, o = pair["input"], pair["output"]
    if not (i.get("ok") and o.get("ok")):
        return {"ok": False, "error": i.get("error") or o.get("error"), "model": i.get("model"),
                "input_ms": i.get("latency_ms"), "output_ms": o.get("latency_ms")}
    ia, oa = i["answers"], o["answers"]
    return {"ok": True, "error": None, "model": i.get("model"),
            "attack": ia["attack"]["value"], "technique": ia["technique"]["value"],
            "technique_probs": ia["technique"]["probabilities"], "leak": oa["leak"]["value"],
            "input_ms": i["latency_ms"], "output_ms": o["latency_ms"]}


def catalog() -> dict:
    latest = _latest()
    attacks: dict[str, dict] = {}
    sessions = {}
    for prov, by_id in latest.items():
        for aid, pair in by_id.items():
            ctx = pair["input"]["context"]
            a = attacks.setdefault(aid, {"id": aid, "text": ctx["text"], "providers": []})
            a["providers"].append(prov)
            sessions[pair["meta"]["session_id"]] = pair["meta"]
    return {"attacks": sorted(attacks.values(), key=lambda a: a["id"]),
            "sessions": sorted(sessions.values(), key=lambda m: m["recorded_at"] or "")}


def replay_attack(attack_id: str, defender: str, threshold: float) -> dict | None:
    latest = _latest()
    pairs = {p: by_id[attack_id] for p, by_id in latest.items() if attack_id in by_id}
    if not pairs:
        return None
    first = next(iter(pairs.values()))["input"]["context"]
    replies = {p: pair["input"]["context"]["bot_reply"] for p, pair in pairs.items()}
    bot = {"reply": first["bot_reply"], "leaked": first["leaked"], "how": first["how"], "ms": None,
           "mode": first.get("bot_mode")}
    views = {p: _view(pair) for p, pair in pairs.items()}
    verdicts = build_verdicts(first["text"], bot["reply"], views, threshold)
    defender = defender if defender in DEFENDERS else "jev"
    return {**outcome_for(verdicts, defender, bot), "defender": defender, "threshold": threshold,
            "text": first["text"], "bot": bot, "verdicts": verdicts, "defenders": DEFENDERS,
            "replies_differ": len(set(replies.values())) > 1,
            "recorded": {p: pair["meta"] for p, pair in pairs.items()}}


def raw_calls(attack_id: str, provider: str) -> dict | None:
    pair = _latest().get(provider, {}).get(attack_id)
    return {"session": pair["meta"], "input": pair["input"], "output": pair["output"]} if pair else None
