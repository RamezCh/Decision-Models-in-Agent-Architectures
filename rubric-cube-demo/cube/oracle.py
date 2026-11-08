"""
Exact "moves to solved" oracle for shallow scrambles.

This is the referee of the race: for every move an AI makes, we know whether it
brought the cube closer to solved (distance went down), was optimal (distance
went down by exactly one, the best possible), or made things worse.

How it works (meet-in-the-middle):
  * At start-up, a breadth-first search from the solved cube records every
    state within TABLE_DEPTH moves, with its exact distance (~47k states, <1 s).
  * To measure a state, we search forward FORWARD_DEPTH moves from it and look
    each result up in that table. distance = min(k + table[state after k moves]).
  This is exact for any state up to TABLE_DEPTH + FORWARD_DEPTH = 7 moves from
  solved. Beyond that, distance() returns None ("more than 7").

Metric: half-turn metric (U, U', U2 each count as one move), the same move set
the AI agents choose from.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .cube_state import ALL_MOVES, MOVE_PERMS, solved_state

TABLE_DEPTH = 4
FORWARD_DEPTH = 3
MAX_EXACT = TABLE_DEPTH + FORWARD_DEPTH

_PERMS = np.array([MOVE_PERMS[m] for m in ALL_MOVES], dtype=np.int64)  # (18, 54)


def _expand(states: np.ndarray) -> np.ndarray:
    """All 18 successors of each row in `states` (N, 54) -> (N*18, 54)."""
    return states[:, _PERMS].reshape(-1, 54)


@lru_cache(maxsize=1)
def _table() -> dict[bytes, int]:
    start = np.array([solved_state()], dtype=np.uint8)
    table = {start[0].tobytes(): 0}
    frontier = start
    for depth in range(1, TABLE_DEPTH + 1):
        nxt = []
        for row in _expand(frontier):
            key = row.tobytes()
            if key not in table:
                table[key] = depth
                nxt.append(row)
        frontier = np.array(nxt, dtype=np.uint8)
    return table


def distance(state) -> int | None:
    """Exact number of moves to solve `state`, or None if it is more than MAX_EXACT."""
    table = _table()
    frontier = np.array([state], dtype=np.uint8)
    for k in range(FORWARD_DEPTH + 1):
        hits = [table[row.tobytes()] for row in frontier if row.tobytes() in table]
        if hits:
            # Exact: with true distance d > TABLE_DEPTH, no hit can appear before
            # k = d - TABLE_DEPTH (it would prove d is smaller), and at that k the
            # optimal path passes a table state worth exactly TABLE_DEPTH.
            return k + min(hits)
        if k < FORWARD_DEPTH:
            frontier = np.unique(_expand(frontier), axis=0)
    return None


def evaluate_moves(state, moves=ALL_MOVES) -> dict:
    """Distance before, and distance after each candidate move.

    Returns {"distance": d, "after": {move: d_after}, "optimal": [moves with d_after == d-1]}.
    """
    from .cube_state import apply_move

    d = distance(state)
    after = {m: distance(apply_move(state, m)) for m in moves}
    optimal = [m for m, v in after.items() if d is not None and v is not None and v == d - 1]
    return {"distance": d, "after": after, "optimal": optimal}


def warm_up() -> int:
    """Build the lookup table now (otherwise it is built on first use). Returns its size."""
    return len(_table())
