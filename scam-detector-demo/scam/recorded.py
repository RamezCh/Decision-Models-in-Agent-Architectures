"""
Read recorded scam-detector answers (written by scam-detector-demo/record.py).

Used by the web app (replay) and by evaluate.py (metrics), so the numbers on a
slide and the replay on screen always come from the same calls.

For each model and listing, the most recent SUCCESSFUL recording wins. A failed
call is only used if there is no successful one (so the replay can show it).
Recordings whose listing text was edited afterwards are ignored.
"""

from __future__ import annotations

import statistics

from system_one.recordings import load_sessions, session_meta

from .detector import OVERALL, RED_FLAGS, assemble, combine, listing_hash, load_examples, model_entry


def latest_calls() -> dict[str, dict[str, dict]]:
    """{provider: {listing_id: {"call": call_line, "meta": session_meta}}}"""
    current = {x["id"]: listing_hash(x) for x in load_examples()}
    out: dict[str, dict[str, dict]] = {}
    for session in load_sessions("scam"):
        meta = session_meta(session)
        for call in session["calls"]:
            ctx = call.get("context", {})
            lid = ctx.get("listing_id")
            if lid not in current or ctx.get("text_sha") != current[lid]:
                continue
            slot = out.setdefault(call["provider"], {})
            if call.get("ok") or lid not in slot:
                slot[lid] = {"call": call, "meta": meta}
    return out


def _probs(call: dict) -> dict[str, float]:
    return {k: a["value"] for k, a in (call.get("answers") or {}).items()}


def _entry(call: dict) -> dict:
    return model_entry(bool(call.get("ok")), _probs(call), call.get("latency_ms", 0.0),
                       call.get("server_ms"), call.get("model"), call.get("error"))


def replay_listing(listing_id: str) -> dict | None:
    calls = latest_calls()
    models, recorded = {}, {}
    for prov in ("jev", "clm"):
        hit = calls.get(prov, {}).get(listing_id)
        if hit:
            models[prov] = _entry(hit["call"])
            recorded[prov] = hit["meta"]
    if not models:
        return None
    out = assemble(models)
    out["recorded"] = recorded
    return out


def raw_calls(listing_id: str, provider: str) -> dict | None:
    hit = latest_calls().get(provider, {}).get(listing_id)
    return {"session": hit["meta"], "call": hit["call"]} if hit else None


def catalog() -> dict:
    """Which listings are recorded, by which models, plus an honest summary over ALL of them."""
    examples = {x["id"]: x for x in load_examples()}
    calls = latest_calls()
    summary, sessions = {}, {}
    for prov, by_id in calls.items():
        ok = [(lid, h["call"]) for lid, h in by_id.items() if h["call"].get("ok")]
        correct = 0
        for lid, call in ok:
            flagged = combine({f["id"]: _probs(call)[f["id"]] for f in RED_FLAGS})["decision"] != "ok"
            correct += flagged == (examples[lid]["label"] == "scam")
        lat = sorted(c.get("latency_ms", 0.0) for _, c in ok)
        summary[prov] = {
            "listings": len(by_id), "answered": len(ok), "correct": correct,
            "median_ms": statistics.median(lat) if lat else None,
            "p95_ms": lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else None,
        }
        for h in by_id.values():
            sessions[h["meta"]["session_id"]] = h["meta"]
    listings = [{"id": lid, "providers": sorted(p for p in calls if lid in calls[p])} for lid in examples]
    return {"listings": [x for x in listings if x["providers"]], "summary": summary,
            "sessions": sorted(sessions.values(), key=lambda m: m["recorded_at"] or ""),
            "overall_id": OVERALL["id"]}
