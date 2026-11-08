"""
Berlin rental-scam detector, built from small yes/no questions.

Instead of asking one big question ("is this a scam?"), we ask each model the
red-flag questions a careful flat-hunter would check, then combine the answers
in ordinary, readable code. Both models get the identical request.

Combining (noisy-OR): each red flag is an independent reason for suspicion.

    risk = 1 - Π (1 - strength_i * P(flag_i))

A flag the model is sure about (P≈1) with strength 0.6 alone gives risk 0.6.
Two medium flags add up. No flag at all gives risk ≈ 0. Students can replace
this with a logistic regression fitted on the labelled data (see evaluate.py).

We ALSO ask the one big question ("This listing is a scam") so the audience can
compare "one big question" against "checklist + code".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "listings.jsonl"

# id, short label for the UI, the statement sent to the model, strength in [0, 1]
RED_FLAGS = [
    {"id": "pay_before_viewing", "label": "Money before viewing",
     "question": "The landlord asks for money (deposit, fee or rent) before the tenant has seen the flat in person or signed a contract.",
     "strength": 0.60},
    {"id": "cannot_show", "label": "Landlord can't show the flat",
     "question": "The landlord says they cannot show the flat in person, for example because they live or work abroad.",
     "strength": 0.50},
    {"id": "keys_by_post", "label": "Keys by post / 'trustee' service",
     "question": "The landlord proposes sending the keys by post or courier, or using a third-party 'trustee', escrow or payment-protection service for the handover.",
     "strength": 0.60},
    {"id": "off_platform", "label": "Moves to WhatsApp / odd payment",
     "question": "The message pushes contact or payment away from the platform, e.g. to WhatsApp, a private email, Western Union, crypto or gift cards.",
     "strength": 0.35},
    {"id": "too_cheap", "label": "Suspiciously cheap",
     "question": "The rent is far below what a flat of this size and location in Berlin normally costs.",
     "strength": 0.30},
    {"id": "early_documents", "label": "Wants ID / bank data early",
     "question": "Copies of passport or ID, bank details or payslips are requested before any viewing has happened.",
     "strength": 0.25},
    {"id": "pressure", "label": "Time pressure",
     "question": "The text pressures the tenant to decide or pay very quickly.",
     "strength": 0.20},
    {"id": "sob_story", "label": "Elaborate personal story",
     "question": "The landlord tells an emotional or elaborate personal story to explain an unusual arrangement.",
     "strength": 0.20},
    {"id": "vague_details", "label": "Vague about the flat",
     "question": "The listing is vague about the flat itself: no exact address, floor, condition or practical details.",
     "strength": 0.10},
]

OVERALL = {"id": "overall", "label": "One big question",
           "question": "This rental listing or landlord message is a scam."}

# Decision thresholds on the combined risk (tune them with evaluate.py)
CHECK_AT = 0.30
WARN_AT = 0.60
UNSURE_BAND = (0.35, 0.65)   # a strong flag answered this close to 50/50 -> human review


def listing_state(listing: dict) -> dict:
    """The state both models see. Structured fields first, then the free text."""
    s = {}
    for key, name in (("title", "Listing title"), ("district", "District (Berlin)"),
                      ("rent_eur", "Monthly rent (EUR, warm)"), ("size_m2", "Size (m²)")):
        if listing.get(key) not in (None, ""):
            s[name] = listing[key]
    s["Listing text and landlord messages"] = listing["text"]
    return s


def questions() -> dict:
    q = {f["id"]: {"type": "noul", "instructions": f["question"]} for f in RED_FLAGS}
    q[OVERALL["id"]] = {"type": "noul", "instructions": OVERALL["question"]}
    return q


def combine(flag_probs: dict[str, float]) -> dict:
    """Noisy-OR combination plus a decision. Pure code, fully explainable."""
    keep = 1.0
    contributions = []
    for f in RED_FLAGS:
        p = flag_probs.get(f["id"], 0.0)
        keep *= 1 - f["strength"] * p
        contributions.append({"id": f["id"], "label": f["label"], "p": p,
                              "weight": f["strength"], "push": f["strength"] * p})
    risk = 1 - keep
    unsure = [c["label"] for c in contributions
              if c["weight"] >= 0.5 and UNSURE_BAND[0] <= c["p"] <= UNSURE_BAND[1]]
    if risk >= WARN_AT:
        decision = "warn"
    elif risk >= CHECK_AT or unsure:
        decision = "check"
    else:
        decision = "ok"
    fired = sorted((c for c in contributions if c["p"] >= 0.5), key=lambda c: -c["push"])
    return {"risk": risk, "decision": decision, "fired": [c["label"] for c in fired],
            "unsure": unsure, "contributions": contributions}


def model_entry(ok: bool, probs: dict[str, float] | None, latency_ms: float, server_ms=None,
                model=None, error=None) -> dict:
    """One model's analysis from its raw yes/no probabilities (live or recorded)."""
    entry = {"ok": ok, "error": error, "latency_ms": latency_ms, "server_ms": server_ms, "model": model}
    if ok and probs:
        entry["flags"] = {f["id"]: probs[f["id"]] for f in RED_FLAGS}
        entry["overall"] = probs[OVERALL["id"]]
        entry["combined"] = combine(entry["flags"])
    return entry


def assemble(models: dict[str, dict]) -> dict:
    """Combine per-model entries into the response the web page renders."""
    out = {"flags": RED_FLAGS, "overall_question": OVERALL["question"], "models": models}
    ok = [m for m in models.values() if m["ok"]]
    if len(ok) == 2:
        a, b = ok
        out["agreement"] = {
            "decision": a["combined"]["decision"] == b["combined"]["decision"],
            "flags_agree": sum((a["flags"][f["id"]] >= 0.5) == (b["flags"][f["id"]] >= 0.5)
                               for f in RED_FLAGS),
            "flags_total": len(RED_FLAGS),
        }
    return out


async def analyze_listing(client, listing: dict) -> dict:
    """Live: ask both models the same questions in parallel and combine each model's answers."""
    results = await client.compare(listing_state(listing), questions())
    return assemble({
        name: model_entry(res.ok, {k: a.value for k, a in res.answers.items()}, res.latency_ms,
                          res.server_ms, res.model, res.error)
        for name, res in results.items()
    })


def listing_hash(listing: dict) -> str:
    """Fingerprint of the listing text, so an edited listing never replays an old recording."""
    return hashlib.sha256(listing["text"].encode("utf-8")).hexdigest()[:16]


def load_examples() -> list[dict]:
    with open(DATA, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
