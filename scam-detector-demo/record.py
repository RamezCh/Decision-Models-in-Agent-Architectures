"""
record.py: record both models' answers for every example listing, for replay and evaluation.

Each model is recorded on its own, one listing at a time (never in parallel), so
latencies are clean. Run from the repository root:

    python scam-detector-demo/record.py --providers clm --where "GPU box, BHT"
    python scam-detector-demo/record.py --providers jev --where "Laptop, Berlin"

Output: recordings/scam/<date>-<time>-<provider>.jsonl
Then: the web app replays them (Scam check, "Recorded"), and evaluate.py computes
the metrics from the same files, so the slide numbers and the demo always match.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from scam.detector import listing_hash, listing_state, load_examples, questions  # noqa: E402
from system_one import SystemOneClient  # noqa: E402
from system_one.recordings import Recorder  # noqa: E402


async def record(provider: str, args, client: SystemOneClient):
    listings = load_examples()
    if args.only:
        listings = [x for x in listings if x["id"] in args.only]
    p = client.providers[provider]
    rec = Recorder("scam", provider, where=args.where, note=args.note)
    ping = await client.ping(provider)
    rec.start({"label": p.label, "base_url": p.base_url, "model_requested": p.model}, ping,
              listings=len(listings))
    print(f"{p.label} -> {rec.path}\n  network ping (no model work): {ping.get('median_ms')} ms")
    failures = 0
    for i, listing in enumerate(listings, 1):
        state, qs = listing_state(listing), questions()
        res = await client.ask(provider, state, qs)
        rec.call({"state": state, "questions": qs}, res,
                 {"listing_id": listing["id"], "text_sha": listing_hash(listing)})
        status = f"{res.latency_ms:6.0f} ms" if res.ok else f"ERROR {res.error}"
        print(f"  {i:2d}/{len(listings)} {listing['id']}: {status}")
        failures += not res.ok
        if failures >= 3 and failures == i:
            print("  first 3 calls failed, stopping. Check the model is running and .env is set.")
            break


async def main_async(args):
    client = SystemOneClient()
    try:
        for prov in args.providers:
            await record(prov, args, client)
    finally:
        await client.aclose()


def main():
    ap = argparse.ArgumentParser(description="Record scam-detector answers for replay")
    ap.add_argument("--providers", nargs="+", default=["jev", "clm"], choices=["jev", "clm"])
    ap.add_argument("--only", nargs="+", help="only these listing ids")
    ap.add_argument("--where", help='shown in the replay, e.g. "Laptop, Berlin"')
    ap.add_argument("--note")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
