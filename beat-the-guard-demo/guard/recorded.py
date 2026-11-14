"""
Replay recorded guard verdicts (written by beat-the-guard-demo/record.py).

The recordings hold CLM's RAW message-check scores and timings. Calibration,
the threshold and the active defender are applied at replay time with the same
build_verdicts() as the live game, so moving the slider during a replay is
honest: it re-decides on the recorded scores, it doesn't invent new ones.
"""

from __future__ import annotations

from system_one.recordings import load_sessions, session_meta

from .game import DEFAULT_DEFENDER, DEFENDERS, MODELS, QUESTIONS_VERSION, build_verdicts, outcome_for


def latest() -> dict[str, dict[str, dict]]:
    """{provider: {attack_id: {"call": call, "meta": session_meta}}}, newest successful recording wins."""
    out: dict[str, dict[str, dict]] = {}
    for session in load_sessions("guard"):
        meta = session_meta(session)
        prov = session["header"]["provider"]
        if prov not in MODELS:
            continue  # e.g. an old Jev recording while the guard is set to CLM only
        for call in session["calls"]:
            ctx = call.get("context", {})
            if ctx.get("questions_version") != QUESTIONS_VERSION:
                continue  # recorded with different questions: not comparable
            slot = out.setdefault(prov, {})
            if call.get("ok") or ctx.get("attack_id") not in slot:
                slot[ctx["attack_id"]] = {"call": call, "meta": meta}
    return out


def _view(call: dict) -> dict:
    if not call.get("ok"):
        return {"ok": False, "error": call.get("error"), "model": call.get("model"),
                "input_ms": call.get("latency_ms"), "server_ms": call.get("server_ms")}
    a = call["answers"]
    return {"ok": True, "error": None, "model": call.get("model"),
            "attack": a["attack"]["value"], "technique": a["technique"]["value"],
            "technique_probs": a["technique"]["probabilities"],
            "input_ms": call["latency_ms"], "server_ms": call.get("server_ms")}


def catalog() -> dict:
    attacks, sessions = {}, {}
    for prov, by_id in latest().items():
        for aid, hit in by_id.items():
            ctx = hit["call"]["context"]
            a = attacks.setdefault(aid, {"id": aid, "text": ctx["text"], "providers": []})
            a["providers"].append(prov)
            sessions[hit["meta"]["session_id"]] = hit["meta"]
    return {"attacks": sorted(attacks.values(), key=lambda a: a["id"]),
            "sessions": sorted(sessions.values(), key=lambda m: m["recorded_at"] or "")}


def replay_attack(attack_id: str, defender: str, threshold: float) -> dict | None:
    hits = {p: by_id[attack_id] for p, by_id in latest().items() if attack_id in by_id}
    if not hits:
        return None
    ctx = next(iter(hits.values()))["call"]["context"]
    replies = {h["call"]["context"]["bot_reply"] for h in hits.values()}
    bot = {"reply": ctx["bot_reply"], "leaked": ctx["leaked"], "how": ctx["how"], "ms": None,
           "mode": ctx.get("bot_mode")}
    verdicts = build_verdicts(ctx["text"], bot["reply"], {p: _view(h["call"]) for p, h in hits.items()}, threshold)
    defender = defender if defender in DEFENDERS else DEFAULT_DEFENDER
    return {**outcome_for(verdicts, defender, bot), "defender": defender, "threshold": threshold,
            "text": ctx["text"], "bot": bot, "verdicts": verdicts, "defenders": DEFENDERS,
            "replies_differ": len(replies) > 1, "recorded": {p: h["meta"] for p, h in hits.items()}}


def raw_calls(attack_id: str, provider: str) -> dict | None:
    hit = latest().get(provider, {}).get(attack_id)
    return {"session": hit["meta"], "call": hit["call"]} if hit else None
