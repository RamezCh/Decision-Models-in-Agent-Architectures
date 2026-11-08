"""
record.py: record how Jev and CLM judge a fixed set of attacks, as a backup for the live game.

Beat the Guard is meant to be played live by the audience. This recording is the
safety net: if the network dies, the page can replay these attacks with the
real recorded verdicts and timings. Run from the repository root:

    python beat-the-guard-demo/record.py --providers clm --where "GPU box, BHT"
    python beat-the-guard-demo/record.py --providers jev --where "Laptop, Berlin"

For each attack: the vault bot answers once, then each model makes its two checks
(input, then output) one call at a time. With the default scripted bot the
replies are deterministic, so recordings from different machines line up. With
an LLM bot, each recording stores the reply it judged, and the replay shows
which reply that was.

Attacks live in beat-the-guard-demo/data/attacks.jsonl; add your own.
Output: recordings/guard/<date>-<time>-<provider>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from guard.game import INPUT_QUESTIONS, OUTPUT_QUESTIONS, output_state  # noqa: E402
from guard.vault_bot import VaultBot  # noqa: E402
from system_one import SystemOneClient  # noqa: E402
from system_one.recordings import Recorder  # noqa: E402

ATTACKS = HERE / "data" / "attacks.jsonl"


def load_attacks() -> list[dict]:
    with open(ATTACKS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


async def record(provider: str, args, client: SystemOneClient, bot: VaultBot):
    attacks = load_attacks()
    p = client.providers[provider]
    rec = Recorder("guard", provider, where=args.where, note=args.note)
    ping = await client.ping(provider)
    rec.start({"label": p.label, "base_url": p.base_url, "model_requested": p.model}, ping,
              bot_mode=bot.mode, attacks=len(attacks))
    print(f"{p.label} -> {rec.path}\n  network ping (no model work): {ping.get('median_ms')} ms")
    for a in attacks:
        reply = await bot.reply(a["text"])
        ctx = {"attack_id": a["id"], "text": a["text"], "bot_reply": reply["reply"],
               "leaked": reply["leaked"], "how": reply["how"], "bot_mode": bot.mode}
        r_in = await client.ask(provider, a["text"], INPUT_QUESTIONS)
        rec.call({"state": a["text"], "questions": INPUT_QUESTIONS}, r_in, {**ctx, "check": "input"})
        r_out = await client.ask(provider, output_state(reply["reply"]), OUTPUT_QUESTIONS)
        rec.call({"state": output_state(reply["reply"]), "questions": OUTPUT_QUESTIONS}, r_out,
                 {**ctx, "check": "output"})
        if r_in.ok and r_out.ok:
            print(f"  {a['id']}: attack {r_in.answers['attack'].value:.2f}, leak {r_out.answers['leak'].value:.2f}, "
                  f"{r_in.latency_ms + r_out.latency_ms:.0f} ms")
        else:
            print(f"  {a['id']}: ERROR {r_in.error or r_out.error}")


async def main_async(args):
    client, bot = SystemOneClient(), VaultBot()
    try:
        for prov in args.providers:
            await record(prov, args, client, bot)
    finally:
        await bot.aclose()
        await client.aclose()


def main():
    ap = argparse.ArgumentParser(description="Record guard verdicts for a fixed set of attacks")
    ap.add_argument("--providers", nargs="+", default=["jev", "clm"], choices=["jev", "clm"])
    ap.add_argument("--where", help='shown in the replay, e.g. "Laptop, Berlin"')
    ap.add_argument("--note")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
