"""
Rubik's Cube state representation and move engine.

State: flat list of 54 integers (0-5), one per sticker.
Face order: U(0-8), R(9-17), F(18-26), D(27-35), L(36-44), B(45-53)
(the same facelet order as Kociemba's solver, so states are easy to cross-check).

Face layouts, each viewed from OUTSIDE the cube, row-major:
  U  seen from above, F side at the bottom of the grid
  R  seen from the right, F side on the left
  F  seen from the front, U side on top
  D  seen from below, F side at the TOP of the grid
  L  seen from the left, B side on the left
  B  seen from behind, R side on the left

          0  1  2
          3  4  5
          6  7  8
 36 37 38 18 19 20  9 10 11 45 46 47
 39 40 41 21 22 23 12 13 14 48 49 50
 42 43 44 24 25 26 15 16 17 51 52 53
         27 28 29
         30 31 32
         33 34 35

Color encoding: 0=White(U), 1=Red(R), 2=Green(F), 3=Yellow(D), 4=Orange(L), 5=Blue(B)
(the standard Western color scheme: white opposite yellow, green opposite blue,
red opposite orange).

Why moves are generated instead of hand-written
-----------------------------------------------
The first version of this file listed every move as hand-typed 4-cycles. Three
of the six were wrong (U and D turned the wrong way, and B mixed up edge and
corner stickers, which produced cubes that can never be solved). Simple tests
such as "M applied 4 times = identity" can't catch this, because ANY 4-cycle
passes them. So every move here is derived from 3D geometry: each sticker gets
a position and a normal vector, the layer is rotated 90°, and we read off
where each sticker landed. The tests compare against known facelet strings.
"""

from __future__ import annotations

FACES = "URFDLB"
FACE_COLORS = {0: "W", 1: "R", 2: "G", 3: "Y", 4: "O", 5: "B"}
COLOR_NAMES = {0: "White", 1: "Red", 2: "Green", 3: "Yellow", 4: "Orange", 5: "Blue"}
FACE_NAMES = {"U": "top", "R": "right", "F": "front", "D": "bottom", "L": "left", "B": "back"}

# ── 3D model ──────────────────────────────────────────────────────
# Axes: x points to R, y points to U, z points to F. Coordinates in {-1, 0, 1}.


def _sticker_geometry(face: str, r: int, c: int):
    """(position, normal) of sticker (row r, col c) on `face`, per the layout above."""
    if face == "U":
        return (c - 1, 1, r - 1), (0, 1, 0)
    if face == "D":
        return (c - 1, -1, 1 - r), (0, -1, 0)
    if face == "F":
        return (c - 1, 1 - r, 1), (0, 0, 1)
    if face == "B":
        return (1 - c, 1 - r, -1), (0, 0, -1)
    if face == "R":
        return (1, 1 - r, 1 - c), (1, 0, 0)
    if face == "L":
        return (-1, 1 - r, c - 1), (-1, 0, 0)
    raise ValueError(face)


_INDEX = {}
for _fi, _f in enumerate(FACES):
    for _r in range(3):
        for _c in range(3):
            _INDEX[_sticker_geometry(_f, _r, _c)] = _fi * 9 + _r * 3 + _c

# Turning face X "clockwise" means clockwise as seen looking AT that face,
# i.e. a -90° right-hand rotation about the face's outward axis.
_AXIS = {"U": (1, 1), "D": (1, -1), "R": (0, 1), "L": (0, -1), "F": (2, 1), "B": (2, -1)}


def _rotate(v, axis: int, direction: int):
    x, y, z = v
    s = -direction  # sin(-90° * direction); cos is 0
    if axis == 0:
        return (x, -s * z, s * y)
    if axis == 1:
        return (s * z, y, -s * x)
    return (-s * y, s * x, z)


def _quarter_turn_perm(face: str) -> list[int]:
    """perm[i] = index whose old sticker moves to position i, for one clockwise turn."""
    axis, direction = _AXIS[face]
    perm = list(range(54))
    for (pos, normal), src in _INDEX.items():
        if pos[axis] == direction:  # sticker is on the turning layer
            dst = _INDEX[(_rotate(pos, axis, direction), _rotate(normal, axis, direction))]
            perm[dst] = src
    return perm


def _compose(p: list[int], q: list[int]) -> list[int]:
    """Permutation for 'apply p, then q'."""
    return [p[q[i]] for i in range(54)]


MOVE_PERMS: dict[str, list[int]] = {}
for _f in FACES:
    _p1 = _quarter_turn_perm(_f)
    _p2 = _compose(_p1, _p1)
    MOVE_PERMS[_f] = _p1
    MOVE_PERMS[_f + "2"] = _p2
    MOVE_PERMS[_f + "'"] = _compose(_p2, _p1)

ALL_MOVES = [f + s for f in FACES for s in ("", "'", "2")]


def apply_move(state: list, move: str) -> list:
    """Return new state after applying move (does not modify the original)."""
    perm = MOVE_PERMS[move]
    return [state[i] for i in perm]


def apply_moves(state: list, moves) -> list:
    if isinstance(moves, str):
        moves = moves.split()
    for m in moves:
        state = apply_move(state, m)
    return state


def inverse_move(move: str) -> str:
    if move.endswith("'"):
        return move[0]
    if move.endswith("2"):
        return move
    return move + "'"


def is_solved(state: list) -> bool:
    """True iff each face has all 9 stickers the same color."""
    return all(len(set(state[f * 9:f * 9 + 9])) == 1 for f in range(6))


def solved_state() -> list:
    return [face for face in range(6) for _ in range(9)]


def stickers_in_place(state: list) -> int:
    """How many of the 54 stickers match their face's center (54 = solved)."""
    return sum(state[i] == state[(i // 9) * 9 + 4] for i in range(54))


def state_to_dict(state: list) -> dict:
    return {FACES[f]: [state[f * 9 + i] for i in range(9)] for f in range(6)}


def to_facelet_string(state: list) -> str:
    """Kociemba-style string, e.g. 'UUUUUUUUURRR...'. Useful for cross-checking."""
    return "".join(FACES[c] for c in state)


def render_state(state: list) -> str:
    """ASCII render of the unfolded cube (net)."""
    d = state_to_dict(state)
    c = FACE_COLORS

    def row(face, r):
        return " ".join(c[d[face][r * 3 + i]] for i in range(3))

    pad = " " * 8
    lines = [pad + row("U", r) for r in range(3)]
    lines += ["  ".join(row(f, r) for f in "LFRB") for r in range(3)]
    lines += [pad + row("D", r) for r in range(3)]
    return "\n".join(lines)
