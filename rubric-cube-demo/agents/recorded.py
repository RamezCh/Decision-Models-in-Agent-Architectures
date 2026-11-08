"""
Replay recorded cube games (written by runner/record.py).

Cubes are identified by (level, seed): the same pair always means the same
scramble, so games recorded by different players on different machines line up.
For each player and cube, the most recent complete game wins (a game that
stopped on an error is only used if there is nothing better).

`catalog()` also summarises EVERY recorded game per level, so the audience sees
the overall picture and not just the one cube on screen (no cherry-picking).
"""

from __future__ import annotations

import statistics

from system_one.recordings import load_sessions, session_meta

_STEP_KEYS = ("step", "move", "ok", "error", "model", "latency_ms", "server_ms", "confidence", "probabilities",
              "verdict", "distance_before", "distance_after", "optimal_moves", "state_after", "solved")


def _games() -> dict[tuple[int, int], dict[str, dict]]:
    """{(level, seed): {player: {"start", "end", "calls", "meta"}}}"""
    games: dict[tuple[int, int], dict[str, dict]] = {}
    for session in load_sessions("cube"):
        meta = session_meta(session)
        player = session["header"]["provider"]
        by_key: dict[tuple[int, int], dict] = {}
        for ev in session["events"]:
            if ev["type"] in ("run_start", "run_end"):
                g = by_key.setdefault((ev["level"], ev["seed"]), {"calls": []})
                g["start" if ev["type"] == "run_start" else "end"] = ev
        for call in session["calls"]:
            ctx = call["context"]
            by_key.setdefault((ctx["level"], ctx["seed"]), {"calls": []})["calls"].append(call)
        for key, g in by_key.items():
            if "start" not in g:
                continue
            g["meta"] = meta
            complete = "end" in g and not g["end"].get("error")
            slot = games.setdefault(key, {})
            if complete or player not in slot:
                slot[player] = g
    return games


def _steps(game: dict) -> list[dict]:
    out = []
    for call in sorted(game["calls"], key=lambda c: c["seq"]):
        merged = {**call["context"], **{k: call.get(k) for k in ("ok", "error", "model", "latency_ms", "server_ms")}}
        out.append({k: merged.get(k) for k in _STEP_KEYS})
    return out


def _summary(step_lists: list[list[dict]]) -> dict:
    moves = [s for steps in step_lists for s in steps if s["ok"]]
    lat = [s["latency_ms"] for s in moves]
    return {"games": len(step_lists),
            "solved": sum(bool(steps and steps[-1].get("solved")) for steps in step_lists),
            "moves": len(moves),
            "optimal_rate": sum(s["verdict"] == "optimal" for s in moves) / len(moves) if moves else None,
            "median_ms": statistics.median(lat) if lat else None,
            "errors": sum(any(not s["ok"] for s in steps) for steps in step_lists)}


def catalog() -> dict:
    games = _games()
    levels: dict[int, dict] = {}
    sessions = {}
    for (level, seed), players in sorted(games.items()):
        lv = levels.setdefault(level, {"seeds": [], "players": set(), "steps": {}})
        lv["seeds"].append(seed)
        for player, g in players.items():
            lv["players"].add(player)
            lv["steps"].setdefault(player, []).append(_steps(g))
            sessions[g["meta"]["session_id"]] = g["meta"]
    return {
        "levels": {lvl: {"seeds": v["seeds"], "players": sorted(v["players"]),
                         "summary": {p: _summary(s) for p, s in v["steps"].items()}}
                   for lvl, v in levels.items()},
        "sessions": sorted(sessions.values(), key=lambda m: m["recorded_at"] or ""),
    }


def replay_game(level: int, seed: int) -> dict | None:
    players = _games().get((level, seed))
    if not players:
        return None
    start = next(iter(players.values()))["start"]
    return {"level": level, "seed": seed, "initial_state": start["initial_state"], "scramble": start["scramble"],
            "max_steps": start.get("max_steps", 3 * level + 4),
            "players": {p: {"steps": _steps(g), "recorded": g["meta"],
                            "result": {k: v for k, v in g.get("end", {}).items() if k not in ("type", "session_id")}}
                        for p, g in players.items()}}


def raw_game(level: int, seed: int, player: str) -> dict | None:
    g = _games().get((level, seed), {}).get(player)
    if not g:
        return None
    return {"session": g["meta"], "run_start": g["start"], "run_end": g.get("end"),
            "calls": sorted(g["calls"], key=lambda c: c["seq"])}
