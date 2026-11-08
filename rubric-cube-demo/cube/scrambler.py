"""
Deterministic cube scrambler.

Given a seed, it produces the same scramble every time, so every agent starts
from an identical cube.

Important for the demo: a random 20-move scramble is far beyond what any
one-move-at-a-time decision model can solve (and a random 20-move sequence is
usually NOT 20 moves from solved anyway). So the race uses `scramble_exact`,
which returns a cube that is exactly `distance` moves from solved, checked by
the oracle. "Level 3" really means "3 perfect moves solve it".
"""

from __future__ import annotations

import random

from .cube_state import ALL_MOVES, apply_move, solved_state
from .oracle import MAX_EXACT, distance

OPPOSITE = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}


def scramble(seed: int = 42, depth: int = 20) -> tuple[list, list]:
    """Random scramble of `depth` moves. Returns (state, moves_applied)."""
    rng = random.Random(seed)
    state = solved_state()
    moves_applied: list[str] = []
    for _ in range(depth):
        prev = moves_applied[-1][0] if moves_applied else None
        prev2 = moves_applied[-2][0] if len(moves_applied) > 1 else None
        candidates = [
            m for m in ALL_MOVES
            if m[0] != prev
            # avoid "U D U" style sequences, which collapse to fewer moves
            and not (prev and prev2 and OPPOSITE[m[0]] == prev and m[0] == prev2)
        ]
        move = rng.choice(candidates)
        state = apply_move(state, move)
        moves_applied.append(move)
    return state, moves_applied


def scramble_exact(distance_to_solved: int, seed: int = 42, max_tries: int = 500) -> tuple[list, list]:
    """A scramble whose TRUE distance to solved is exactly `distance_to_solved` (1..7)."""
    if not 1 <= distance_to_solved <= MAX_EXACT:
        raise ValueError(f"distance must be between 1 and {MAX_EXACT}")
    for attempt in range(max_tries):
        state, moves = scramble(seed=seed * 1000 + attempt, depth=distance_to_solved)
        if distance(state) == distance_to_solved:
            return state, moves
    raise RuntimeError("could not generate a scramble of that exact distance")
