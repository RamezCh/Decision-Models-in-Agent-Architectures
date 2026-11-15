"""
How should CLM be asked about the cube? Measures each design on real positions.

    python tools/tune_cube.py            (tunnel to CLM open, from the repository root)

Uses 21 cubes that are 1, 2 or 3 moves from solved (7 each). Per design it prints:
  * how often CLM's top move is optimal (the perfect solver decides), vs a random move
  * the median rank CLM gives the best move (1 = it put an optimal move first, of 18)
  * how many DIFFERENT moves it picked over the 21 cubes, and its favourite's share.
    "1 different move, 100% F2" means it ignores the cube and always gives the same answer.

The demo uses CUBE_CLM_DESIGN (default "short"); set it in .env to switch.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "rubric-cube-demo"):
    sys.path.insert(0, str(ROOT / sub))

from agents.players import CUBE_DESIGN, CUBE_DESIGNS, cube_request, legal_moves  # noqa: E402
from cube.oracle import evaluate_moves  # noqa: E402
from cube.scrambler import scramble_exact  # noqa: E402
from system_one.client import SystemOneClient  # noqa: E402


async def run(provider: str, designs: list[str]):
    cubes = []
    for level in (1, 2, 3):
        for seed in range(1, 8):
            state, _ = scramble_exact(level, seed=seed)
            moves = legal_moves(None)
            cubes.append((state, moves, set(evaluate_moves(state, moves)["optimal"])))
    chance = statistics.mean(len(opt) / len(moves) for _, moves, opt in cubes)
    print(f"{len(cubes)} cubes, 1-3 moves from solved. A random move is optimal {chance:.0%} of the time.")
    client = SystemOneClient()
    try:
        for d in designs:
            results = await asyncio.gather(*(client.ask(provider, **cube_request(s, None, m, design=d))
                                             for s, m, _ in cubes))
            bad = [r.error for r in results if not r.ok]
            if bad:
                print(f"\n{d}: {len(bad)} failed, e.g. {bad[0]}")
                continue
            tops, ranks, hits = [], [], 0
            for r, (_, _, opt) in zip(results, cubes):
                probs = r.answers["next_move"].probabilities
                order = sorted(probs, key=probs.get, reverse=True)
                tops.append(order[0])
                hits += order[0] in opt
                ranks.append(min(order.index(m) for m in opt) + 1)
            fav, n_fav = Counter(tops).most_common(1)[0]
            tag = "   <- used by the demo" if d == CUBE_DESIGN else ""
            print(f"\n{d}: {CUBE_DESIGNS[d]}{tag}")
            print(f"  top move optimal: {hits}/{len(cubes)} ({hits / len(cubes):.0%})   "
                  f"median rank of the best move: {statistics.median(ranks):g} of 18")
            print(f"  picked {len(set(tops))} different moves; favourite {fav} {n_fav / len(cubes):.0%} of the time")
    finally:
        await client.aclose()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", default="clm")
    ap.add_argument("--designs", nargs="+", default=list(CUBE_DESIGNS), choices=list(CUBE_DESIGNS))
    a = ap.parse_args()
    asyncio.run(run(a.provider, a.designs))


if __name__ == "__main__":
    main()
