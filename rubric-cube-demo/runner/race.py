"""
race.py: live command-line Rubik's Cube race. To record runs for replay, use record.py.

Run from the rubric-cube-demo folder:

    python -m runner.race --level 3 --players jev clm random oracle

Every player starts from the same cube, exactly LEVEL moves from solved. After
each move the exact solver (cube/oracle.py) judges it:

    optimal   the move reduced the distance to solved by one (best possible)
    worse     the move increased the distance
    neutral   anything else
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))  # for the shared system_one package

from agents.players import PLAYERS, play  # noqa: E402
from cube.oracle import warm_up  # noqa: E402
from cube.cube_state import render_state  # noqa: E402
from cube.scrambler import scramble_exact  # noqa: E402


def print_step(rec: dict, _res: dict):
    if not rec["ok"]:
        print(f"  step {rec['step']:2d} | ERROR: {rec['error']}")
        return
    d = "?" if rec["distance_after"] is None else rec["distance_after"]
    tag = rec["verdict"] if rec["verdict"] != "neutral" else ""
    print(f"  step {rec['step']:2d} | {rec['move']:3s} | {rec['latency_ms']:7.1f} ms | "
          f"conf {rec['confidence']:.2f} | distance -> {d:>2} {tag}")


async def main_async(args):
    warm_up()
    state, scramble_moves = scramble_exact(args.level, seed=args.seed)
    print(f"Scramble (level {args.level}, seed {args.seed}): {' '.join(scramble_moves)}")
    print(render_state(state))

    client = None
    if any(p in ("jev", "clm") for p in args.players):
        from system_one import SystemOneClient
        client = SystemOneClient()
    results = {}
    try:
        for name in args.players:
            print(f"\n── {PLAYERS[name]} " + "─" * (50 - len(PLAYERS[name])))
            results[name] = await play(name, state, client, args.max_steps, not args.allow_same_face,
                                       random.Random(args.seed), print_step, no_repeat=not args.allow_repeats)
    finally:
        if client:
            await client.aclose()

    print("\n" + "=" * 70)
    print(f"{'player':<16}{'solved':<8}{'moves':<7}{'optimal':<9}{'median ms':<11}error")
    for name, r in results.items():
        lat = [s["latency_ms"] for s in r["steps"] if s["ok"]]
        med = f"{statistics.median(lat):.0f}" if lat else "-"
        print(f"{PLAYERS[name]:<16}{str(r['solved']):<8}{r['moves']:<7}{r['optimal_rate']:<9.0%}{med:<11}{r['error'] or ''}")


def main():
    ap = argparse.ArgumentParser(description="Rubik's Cube race: Jev vs CLM (+ baselines), live")
    ap.add_argument("--level", type=int, default=3, help="exact moves from solved, 1-7 (default 3)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--players", nargs="+", default=["jev", "clm", "random", "oracle"], choices=list(PLAYERS))
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--allow-repeats", action="store_true",
                    help="let players return to a position they were already in (off by default: it causes loops)")
    ap.add_argument("--allow-same-face", action="store_true",
                    help="let models turn the same face twice in a row (off by default)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
