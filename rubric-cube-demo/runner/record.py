"""
record.py: record cube games for replay in the web app.

Each player is recorded on its own, one call at a time (never two models in
parallel), so the latencies are not affected by anything else running. Run it
from the rubric-cube-demo folder:

    python -m runner.record --players clm --levels 2 3 4 --cubes 10 --where "GPU box, BHT"
    python -m runner.record --players jev --levels 2 3 4 --cubes 10 --where "Laptop, Berlin"
    python -m runner.record --players random oracle --levels 2 3 4 --cubes 10

Cube number k at level L always has the same scramble (seed = first_seed + k),
so recordings made on different machines or days line up cube by cube.

Output: recordings/cube/<date>-<time>-<player>.jsonl (see system_one/recordings.py).
The web app replays the most recent recording of each player for each cube.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from agents.players import PLAYERS, play  # noqa: E402
from cube.oracle import warm_up  # noqa: E402
from cube.scrambler import scramble_exact  # noqa: E402
from system_one.recordings import Recorder  # noqa: E402


async def record_player(name: str, args, client) -> str:
    rec = Recorder("cube", name, where=args.where, note=args.note)
    info, ping = None, None
    if client is not None:
        p = client.providers[name]
        info = {"label": p.label, "base_url": p.base_url, "model_requested": p.model}
        ping = await client.ping(name)
    rec.start(info, ping, constrain=not args.allow_same_face, no_repeat=not args.allow_repeats,
              max_steps=args.max_steps)
    print(f"\n{PLAYERS[name]} -> {rec.path}")
    if ping:
        print(f"  network ping (no model work): {ping.get('median_ms')} ms")

    for level in args.levels:
        for k in range(args.cubes):
            seed = args.first_seed + k
            state, scramble = scramble_exact(level, seed=seed)
            max_steps = args.max_steps
            rec.event("run_start", level=level, seed=seed, initial_state=state, scramble=scramble,
                      max_steps=max_steps)

            def log_step(step, decision, level=level, seed=seed):
                fields = {k: decision[k] for k in ("ok", "error", "model", "server_ms", "answers")}
                fields["latency_ms"] = round(decision["latency_ms"], 2)
                context = {"level": level, "seed": seed,
                           **{k: v for k, v in step.items() if k not in ("latency_ms", "server_ms", "model", "error", "ok")}}
                rec.call(decision["request"], None, context, **fields)

            result = await play(name, state, client, max_steps, not args.allow_same_face,
                                random.Random(seed), log_step, no_repeat=not args.allow_repeats)
            rec.event("run_end", level=level, seed=seed, solved=result["solved"], moves=result["moves"],
                      optimal_rate=result["optimal_rate"], final_distance=result["final_distance"],
                      error=result["error"])
            status = "solved" if result["solved"] else f"distance {result['final_distance']}"
            print(f"  level {level} cube {k + 1}/{args.cubes}: {result['moves']} moves, "
                  f"{result['optimal_rate']:.0%} optimal, {status}" + (f"  ERROR: {result['error']}" if result["error"] else ""))
            if result["error"] and args.stop_on_error:
                print("  stopping (use --keep-going to continue after errors)")
                return str(rec.path)
    return str(rec.path)


async def main_async(args):
    warm_up()
    client = None
    if any(p in ("jev", "clm") for p in args.players):
        from system_one import SystemOneClient
        client = SystemOneClient()
    try:
        for name in args.players:
            await record_player(name, args, client if name in ("jev", "clm") else None)
    finally:
        if client:
            await client.aclose()


def main():
    ap = argparse.ArgumentParser(description="Record cube games for replay")
    ap.add_argument("--players", nargs="+", default=["jev", "clm", "random", "oracle"], choices=list(PLAYERS))
    ap.add_argument("--levels", nargs="+", type=int, default=[2, 3, 4])
    ap.add_argument("--cubes", type=int, default=10, help="cubes per level (default 10)")
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--where", help='shown in the replay, e.g. "Laptop, Berlin" or "GPU box, BHT"')
    ap.add_argument("--note", help="free text stored with the recording")
    ap.add_argument("--allow-same-face", action="store_true")
    ap.add_argument("--max-steps", type=int, default=60,
                    help="moves allowed per cube before giving up (default 60)")
    ap.add_argument("--allow-repeats", action="store_true",
                    help="let players return to a position they were already in (off by default: it causes loops)")
    ap.add_argument("--keep-going", dest="stop_on_error", action="store_false",
                    help="continue with the next cube after a failed call")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
