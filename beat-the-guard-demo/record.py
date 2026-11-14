"""
record.py: record CLM's message check on the labelled messages, for calibration and as a backup.

Two uses:
  * calibration: tools/calibrate.py fits CLM's raw "is this an attack?" scores to
    the labels in data/attacks.jsonl (13 attacks, 12 harmless messages)
  * backup: if the network fails during the live game, the page replays these
    messages with the real recorded verdicts and timings

Run from the repository root, with the tunnel to CLM open:

    python beat-the-guard-demo/record.py --where "BHT cluster (A100)"

For each message: the vault bot answers, then the model makes its message check
(one call). The answer check is plain code, so it needs no recording. With the
default scripted bot the replies are deterministic, so recordings line up.

Output: recordings/guard/<date>-<time>-<provider>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from guard.game import INPUT_QUESTIONS, MODELS, QUESTIONS_VERSION, load_attacks  # noqa: E402
from guard.vault_bot import VaultBot  # noqa: E402
from system_one import SystemOneClient  # noqa: E402
from system_one.recordings import Recorder  # noqa: E402


async def record(provider: str, args, client: SystemOneClient, bot: VaultBot):
    attacks = load_attacks()
    p = client.providers[provider]
    rec = Recorder("guard", provider, where=args.where, note=args.note)
    ping = await client.ping(provider)
    rec.start({"label": p.label, "base_url": p.base_url, "model_requested": p.model}, ping,
              bot_mode=bot.mode, attacks=len(attacks), questions_version=QUESTIONS_VERSION)
    print(f"{p.label} -> {rec.path}\n  network ping (no model work): {ping.get('median_ms')} ms")
    for a in attacks:
        reply = await bot.reply(a["text"])
        res = await client.ask(provider, a["text"], INPUT_QUESTIONS)
        rec.call({"state": a["text"], "questions": INPUT_QUESTIONS}, res,
                 {"attack_id": a["id"], "text": a["text"], "is_attack": a["attack"], "bot_reply": reply["reply"],
                  "leaked": reply["leaked"], "how": reply["how"], "bot_mode": bot.mode,
                  "questions_version": QUESTIONS_VERSION})
        label = "attack  " if a["attack"] else "harmless"
        if res.ok:
            print(f"  {a['id']} {label} raw score {res.answers['attack'].value:.4f}  {res.latency_ms:.0f} ms")
        else:
            print(f"  {a['id']} ERROR {res.error}")


async def main_async(args):
    client, bot = SystemOneClient(), VaultBot()
    try:
        for prov in args.providers:
            await record(prov, args, client, bot)
    finally:
        await bot.aclose()
        await client.aclose()


def main():
    ap = argparse.ArgumentParser(description="Record the guard's message check on the labelled messages")
    ap.add_argument("--providers", nargs="+", default=MODELS, choices=["jev", "clm"])
    ap.add_argument("--where", help='shown in the replay, e.g. "BHT cluster (A100)"')
    ap.add_argument("--note")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
