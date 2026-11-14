"""
Cube-race players: Jev, CLM, and two reference baselines.

  jev     TypeSafe Jev, via the shared System One client
  clm     CLM-8B, via the shared System One client (same request as Jev)
  random  picks a random legal move: the "no intelligence" floor
  oracle  always picks an optimal move (using the exact solver): the ceiling

Both AI models get the identical state text, question and 18 (or 15) option
texts. The surrounding code only does two things, which is the "smart
if-statement" pattern from the talk: it decides which moves are legal, and it
applies the chosen move.

`play()` runs one whole game and is shared by the live web race, the CLI race
and the recorder, so every mode judges moves exactly the same way.
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict
from typing import Any, Callable

from cube.cube_state import (ALL_MOVES, COLOR_NAMES, FACE_NAMES, FACES, apply_move, is_solved,
                             stickers_in_place)
from cube.oracle import evaluate_moves

PLAYERS = {
    "jev": "Jev (TypeSafe)",
    "clm": "CLM-8B",
    "random": "Random mover",
    "oracle": "Perfect solver",
}

_TURN = {"": "a quarter turn clockwise", "'": "a quarter turn counter-clockwise", "2": "a half turn (180°)"}


def move_description(move: str, state: list) -> str:
    face = move[0]
    centre = COLOR_NAMES[state[FACES.index(face) * 9 + 4]].lower()
    return f"{move}: turn the {FACE_NAMES[face]} face ({centre} centre) {_TURN[move[1:]]}"


def legal_moves(last_move: str | None, constrain: bool = True, state: list | None = None,
                visited: set | None = None) -> list[str]:
    """The code-side rules around the model (the model only chooses among what is left):

    * constrain: never turn the same face twice in a row (it is always wasteful)
    * visited:   never return to a position this player was already in. A model that
                 always takes its favourite move otherwise loops forever (e.g. U2, R2,
                 U2, R2...). If every move would revisit, the rule is dropped for that turn.
    """
    moves = list(ALL_MOVES) if not constrain or not last_move else [m for m in ALL_MOVES if m[0] != last_move[0]]
    if visited and state is not None:
        fresh = [m for m in moves if state_key(apply_move(state, m)) not in visited]
        moves = fresh or moves
    return moves


def state_key(state: list) -> bytes:
    return bytes(state)


def state_text(state: list, last_move: str | None) -> str:
    lines = ["A Rubik's cube. Each face is a 3x3 grid of sticker colours, "
             "as seen when looking straight at that face."]
    for fi, face in enumerate(FACES):
        stickers = [COLOR_NAMES[c].lower() for c in state[fi * 9:fi * 9 + 9]]
        lines.append(f"{FACE_NAMES[face].capitalize()} face ({stickers[4]} centre):")
        for r in range(3):
            lines.append("  " + " ".join(stickers[r * 3:r * 3 + 3]))
    lines.append(f"Stickers already matching their face's centre: {stickers_in_place(state)} of 54.")
    lines.append(f"Previous move: {last_move or 'none'}.")
    lines.append("Goal: solve the cube so every face shows a single colour.")
    return "\n".join(lines)


def cube_question(state: list, moves: list[str]) -> dict:
    return {
        "next_move": {
            "type": "choice",
            "instructions": "Which single move brings this Rubik's cube closest to being solved?",
            "criteria": {m: move_description(m, state) for m in moves},
        }
    }


async def decide(player: str, state: list, last_move: str | None, client=None,
                 constrain: bool = True, rng: random.Random | None = None,
                 visited: set | None = None) -> dict[str, Any]:
    """One decision. Everything returned is JSON-serializable (it is logged and sent to the browser)."""
    moves = legal_moves(last_move, constrain, state, visited)
    base = {"request": None, "answers": None, "model": None, "server_ms": None, "error": None}

    if player == "random":
        t0 = time.perf_counter()
        move = (rng or random).choice(moves)
        return {**base, "ok": True, "move": move, "probabilities": {m: 1 / len(moves) for m in moves},
                "confidence": 0.0, "latency_ms": (time.perf_counter() - t0) * 1000}

    if player == "oracle":
        t0 = time.perf_counter()
        ev = evaluate_moves(state, moves)
        best = ev["optimal"] or [min(moves, key=lambda m: ev["after"][m] if ev["after"][m] is not None else 99)]
        return {**base, "ok": True, "move": best[0],
                "probabilities": {m: (1 / len(best) if m in best else 0.0) for m in moves},
                "confidence": 1.0, "latency_ms": (time.perf_counter() - t0) * 1000}

    if player not in ("jev", "clm"):
        raise ValueError(f"unknown player {player!r}")

    request = {"state": state_text(state, last_move), "questions": cube_question(state, moves)}
    res = await client.ask(player, request["state"], request["questions"])
    a = res.answers.get("next_move")
    return {
        "ok": res.ok,
        "move": a.value if (res.ok and a) else None,
        "probabilities": a.probabilities if a else {},
        "confidence": a.confidence if a else 0.0,
        "latency_ms": res.latency_ms,
        "server_ms": res.server_ms,
        "model": res.model,
        "error": res.error,
        "request": request,
        "answers": {k: asdict(v) for k, v in res.answers.items()},
    }


def judge(state: list, move: str, last_move: str | None, constrain: bool = True,
          visited: set | None = None) -> dict:
    """The referee: exact distance before/after and whether the move was optimal."""
    ev = evaluate_moves(state, legal_moves(last_move, constrain, state, visited))
    d, d_after = ev["distance"], ev["after"][move]
    if move in ev["optimal"]:
        verdict = "optimal"
    elif d is not None and (d_after is None or d_after > d):
        verdict = "worse"
    else:
        verdict = "neutral"
    return {"distance_before": d, "distance_after": d_after, "optimal_moves": ev["optimal"], "verdict": verdict}


async def play(player: str, initial_state: list, client=None, max_steps: int = 20, constrain: bool = True,
               rng: random.Random | None = None,
               on_step: Callable[[dict, dict], Any] | None = None, no_repeat: bool = True) -> dict:
    """Play one game until solved, max_steps, or an error. Calls on_step(step_record, decision)."""
    state, last = initial_state[:], None
    visited = {state_key(state)} if no_repeat else None
    steps: list[dict] = []
    for step in range(1, max_steps + 1):
        if is_solved(state):
            break
        res = await decide(player, state, last, client, constrain, rng, visited)
        rec = {"step": step, "state_before": state, "last_move": last, "ok": res["ok"],
               "latency_ms": round(res["latency_ms"], 2), "server_ms": res["server_ms"],
               "model": res["model"], "error": res["error"]}
        if not res["ok"]:
            steps.append(rec)
            if on_step:
                on_step(rec, res)
            break  # stop instead of guessing: a fake move would corrupt the comparison
        new_state = apply_move(state, res["move"])
        rec.update(move=res["move"], confidence=res["confidence"], probabilities=res["probabilities"],
                   state_after=new_state, solved=is_solved(new_state),
                   **judge(state, res["move"], last, constrain, visited))
        steps.append(rec)
        if on_step:
            on_step(rec, res)
        state, last = new_state, res["move"]
        if visited is not None:
            visited.add(state_key(state))

    moves = [s for s in steps if s["ok"]]
    return {
        "steps": steps,
        "solved": is_solved(state),
        "moves": len(moves),
        "optimal_rate": sum(s["verdict"] == "optimal" for s in moves) / len(moves) if moves else 0.0,
        "final_distance": moves[-1]["distance_after"] if moves else None,
        "error": next((s["error"] for s in steps if not s["ok"]), None),
    }
