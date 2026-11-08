"""Unit tests for the Rubik's Cube engine, oracle and scrambler.

Run from the rubric-cube-demo folder:  python -m pytest tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cube.cube_state import (ALL_MOVES, apply_move, apply_moves, inverse_move, is_solved,  # noqa: E402
                             solved_state, stickers_in_place, to_facelet_string)
from cube.oracle import MAX_EXACT, distance, evaluate_moves  # noqa: E402
from cube.scrambler import scramble, scramble_exact  # noqa: E402

SOLVED = solved_state()

# Reference facelet strings (Kociemba order URFDLB) after one move on a solved cube.
# These pin down the DIRECTION of every move and the sticker layout, which the
# old group-property tests could not detect.
KNOWN = {
    "U": "UUUUUUUUUBBBRRRRRRRRRFFFFFFDDDDDDDDDFFFLLLLLLLLLBBBBBB",
    "R": "UUFUUFUUFRRRRRRRRRFFDFFDFFDDDBDDBDDBLLLLLLLLLUBBUBBUBB",
    "F": "UUUUUULLLURRURRURRFFFFFFFFFRRRDDDDDDLLDLLDLLDBBBBBBBBB",
    "D": "UUUUUUUUURRRRRRFFFFFFFFFLLLDDDDDDDDDLLLLLLBBBBBBBBBRRR",
    "L": "BUUBUUBUURRRRRRRRRUFFUFFUFFFDDFDDFDDLLLLLLLLLBBDBBDBBD",
    "B": "RRRUUUUUURRDRRDRRDFFFFFFFFFDDDDDDLLLULLULLULLBBBBBBBBB",
}


def cubie_signature(state):
    """Multiset of sticker-colour tuples per cubie. Any legal move preserves it."""
    corners = [(0, 36, 47), (2, 45, 11), (8, 9, 20), (6, 18, 38),
               (27, 44, 24), (29, 26, 15), (35, 17, 51), (33, 53, 42)]
    edges = [(1, 46), (5, 10), (7, 19), (3, 37), (28, 25), (32, 16), (34, 52), (30, 43),
             (23, 12), (21, 41), (50, 39), (48, 14)]
    return (sorted(tuple(sorted(state[i] for i in c)) for c in corners),
            sorted(tuple(sorted(state[i] for i in e)) for e in edges))


class TestMoves(unittest.TestCase):
    def test_solved(self):
        self.assertTrue(is_solved(SOLVED))
        self.assertEqual(stickers_in_place(SOLVED), 54)

    def test_known_single_moves(self):
        for move, expected in KNOWN.items():
            self.assertEqual(to_facelet_string(apply_move(SOLVED, move)), expected, move)

    def test_inverse_and_double(self):
        for m in ALL_MOVES:
            self.assertEqual(apply_move(apply_move(SOLVED, m), inverse_move(m)), SOLVED, m)
        for f in "URFDLB":
            self.assertEqual(apply_moves(SOLVED, [f, f]), apply_move(SOLVED, f + "2"))

    def test_sexy_move_order_6(self):
        s = SOLVED
        for _ in range(6):
            s = apply_moves(s, "R U R' U'")
        self.assertEqual(s, SOLVED)

    def test_order_of_RU_is_105(self):
        """(R U) has order exactly 105, a classic check that catches subtle move bugs."""
        s, n = apply_moves(SOLVED, "R U"), 1
        while s != SOLVED:
            s, n = apply_moves(s, "R U"), n + 1
        self.assertEqual(n, 105)

    def test_every_move_keeps_cubies_intact(self):
        """Corners stay corners and edges stay edges (the old B move broke this)."""
        ref = cubie_signature(SOLVED)
        state, _ = scramble(seed=7, depth=40)
        self.assertEqual(cubie_signature(state), ref)
        for m in ALL_MOVES:
            self.assertEqual(cubie_signature(apply_move(SOLVED, m)), ref, m)

    def test_scramble_and_invert(self):
        scrambled, moves = scramble(seed=123, depth=15)
        self.assertFalse(is_solved(scrambled))
        s = scrambled
        for m in reversed(moves):
            s = apply_move(s, inverse_move(m))
        self.assertEqual(s, SOLVED)


class TestOracle(unittest.TestCase):
    def test_distances(self):
        self.assertEqual(distance(SOLVED), 0)
        for m in ALL_MOVES:
            self.assertEqual(distance(apply_move(SOLVED, m)), 1)
        self.assertEqual(distance(apply_moves(SOLVED, "R U")), 2)
        self.assertEqual(distance(apply_moves(SOLVED, "R R")), 1)  # R R = R2

    def test_exact_scrambles(self):
        for d in range(1, MAX_EXACT + 1):
            state, moves = scramble_exact(d, seed=d)
            self.assertEqual(distance(state), d)
            self.assertEqual(len(moves), d)

    def test_optimal_moves_reduce_distance(self):
        state, moves = scramble_exact(4, seed=3)
        ev = evaluate_moves(state)
        self.assertEqual(ev["distance"], 4)
        self.assertIn(inverse_move(moves[-1]), ev["optimal"])
        for m in ev["optimal"]:
            self.assertEqual(distance(apply_move(state, m)), 3)

    def test_too_deep_returns_none(self):
        state, _ = scramble(seed=11, depth=25)
        self.assertIsNone(distance(state))


if __name__ == "__main__":
    unittest.main()
