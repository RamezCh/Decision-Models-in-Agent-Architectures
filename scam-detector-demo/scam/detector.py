"""
Berlin rental-scam detector, built from small yes/no questions.

Instead of asking one big question ("is this a scam?"), we ask the red-flag
questions a careful flat-hunter would check, then combine the answers in
ordinary, readable code.

How the questions are written matters for CLM. CLM doesn't read a question and
reason; it compares the listing against each possible ANSWER TEXT and picks the
closest. So every question carries a full-sentence description of what "yes"
and "no" look like. Without them, CLM compares two near-identical sentences
("Yes. This is true: ..." / "No. This is false: ...") and lands near 50/50.
Measured on our 30 labelled listings (tools/diagnose_clm.py): the big question
went from AUC 0.42 (worse than a coin flip) to 0.93 with descriptions.

Combining: CLM ranks well, but its raw percentages are shifted per question
(e.g. 96% on scams vs 93% on legit listings). So the answers are combined by a
small logistic regression CALIBRATED on the labelled listings (tools/calibrate.py
writes data/calibration_<model>.json). Each answer's weight shows how much it
pushes towards "scam" or "legit". Until a calibration exists, a simple noisy-OR
over the raw answers is used, and the page says it is uncalibrated.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from system_one.calibration import predict_combined
from system_one.client import demo_models

# Models this demo asks. CLM only by default; SCAM_MODELS=jev,clm in .env compares both.
MODELS = demo_models("scam")

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data" / "listings.jsonl"

# id, short label, question, what "yes" looks like, what "no" looks like, strength (uncalibrated fallback only)
RED_FLAGS = [
    {"id": "pay_before_viewing", "label": "Money before viewing",
     "question": "Does the landlord ask for money before the tenant has seen the flat or signed a contract?",
     "true": "The landlord wants a deposit, fee or rent transferred before any viewing or signed lease.",
     "false": "Money is only paid after viewing the flat in person and signing the lease.",
     "strength": 0.60},
    {"id": "cannot_show", "label": "Landlord can't show the flat",
     "question": "Does the landlord say they cannot show the flat in person?",
     "true": "The landlord is abroad or unavailable and cannot show the flat in person.",
     "false": "The flat can be viewed in person with the landlord, an agent or a flatmate.",
     "strength": 0.50},
    {"id": "keys_by_post", "label": "Keys by post / 'trustee' service",
     "question": "Will the keys be sent by post or handed over through a third-party trustee or payment-protection service?",
     "true": "Keys are sent by post or courier, or a trustee, escrow or payment-protection service handles money and keys.",
     "false": "Keys are handed over in person when the tenant moves in.",
     "strength": 0.60},
    {"id": "off_platform", "label": "Moves to WhatsApp / odd payment",
     "question": "Does the landlord push contact or payment away from the platform?",
     "true": "The landlord wants to move to WhatsApp or private email, or be paid by Western Union, crypto or gift cards.",
     "false": "Contact stays on the platform and payment is a normal bank transfer after signing.",
     "strength": 0.35},
    {"id": "too_cheap", "label": "Suspiciously cheap",
     "question": "Is the rent far below what a flat of this size and location in Berlin normally costs?",
     "true": "The rent is unrealistically low for the size and location, too good to be true.",
     "false": "The rent is normal or high for the size and location in Berlin.",
     "strength": 0.30},
    {"id": "early_documents", "label": "Wants ID / bank data early",
     "question": "Are ID copies, bank details or payslips requested before any viewing?",
     "true": "Passport or ID copies, bank details or payslips must be sent before seeing the flat.",
     "false": "Documents are only requested after the viewing, or not at all.",
     "strength": 0.25},
    {"id": "pressure", "label": "Time pressure",
     "question": "Does the text pressure the tenant to decide or pay very quickly?",
     "true": "The tenant is pushed to decide or pay immediately, today or within hours.",
     "false": "There is no rush; the tenant can take normal time to decide.",
     "strength": 0.20},
    {"id": "sob_story", "label": "Elaborate personal story",
     "question": "Does the landlord tell an emotional or elaborate personal story to explain an unusual arrangement?",
     "true": "The landlord explains the situation with an emotional personal story such as illness, inheritance, mission work or family trouble.",
     "false": "The listing is matter-of-fact, with no personal story.",
     "strength": 0.20},
    {"id": "vague_details", "label": "Vague about the flat",
     "question": "Is the listing vague about the flat itself?",
     "true": "The listing gives few concrete details about the flat: no exact address, floor or condition.",
     "false": "The listing gives concrete details such as street, floor, condition and viewing times.",
     "strength": 0.10},
]

OVERALL = {"id": "overall", "label": "One big question",
           "question": "Is this rental listing a scam?",
           "true": "This is a rental scam designed to take the tenant's money.",
           "false": "This is a genuine rental offer from a real landlord or agency."}

# Order of the answers fed to the calibration (9 flags, then the big question)
FEATURES = [f["id"] for f in RED_FLAGS] + [OVERALL["id"]]
LABELS = {f["id"]: f["label"] for f in RED_FLAGS} | {OVERALL["id"]: OVERALL["label"]}

# Decision thresholds on the (calibrated) risk
CHECK_AT = 0.30
WARN_AT = 0.60


def listing_state(listing: dict) -> dict:
    """The state the model sees. Structured fields first, then the free text."""
    s = {}
    for key, name in (("title", "Listing title"), ("district", "District (Berlin)"),
                      ("rent_eur", "Monthly rent (EUR, warm)"), ("size_m2", "Size (m²)")):
        if listing.get(key) not in (None, ""):
            s[name] = listing[key]
    s["Listing text and landlord messages"] = listing["text"]
    return s


def questions() -> dict:
    q = {}
    for f in RED_FLAGS + [OVERALL]:
        q[f["id"]] = {"type": "noul", "instructions": f["question"],
                      "criteria": {"true": f["true"], "false": f["false"]}}
    return q


# A calibration only fits the exact questions it was fitted on.
QUESTIONS_VERSION = hashlib.sha256(json.dumps(questions(), sort_keys=True).encode()).hexdigest()[:12]


def calibration_path(model: str) -> Path:
    return HERE / "data" / f"calibration_{model}.json"


@lru_cache(maxsize=8)
def _load_calibration(model: str, mtime: float) -> dict | None:
    try:
        cal = json.loads(calibration_path(model).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cal if cal.get("questions_version") == QUESTIONS_VERSION and cal.get("features") == FEATURES else None


def load_calibration(model: str | None) -> dict | None:
    """The calibration for `model`, or None if missing or made for different questions."""
    if not model:
        return None
    p = calibration_path(model)
    return _load_calibration(model, p.stat().st_mtime) if p.exists() else None


def _reason(c: dict) -> str:
    return f"{c['label']} ({c['answer']})" if "answer" in c else c["label"]


def combine(probs: dict[str, float], model: str | None = None) -> dict:
    """All answers -> risk, decision and the reasons. Pure code, fully explainable."""
    cal = load_calibration(model)
    if cal and all(k in probs for k in FEATURES):
        risk, contrib = predict_combined(cal, [probs[k] for k in FEATURES])
        # was CLM's yes-score for this question higher or lower than usual?
        contributions = [{"id": k, "label": LABELS[k], "p": probs[k], "push": c,
                          "answer": "CLM said yes more than usual" if (c > 0) == (w > 0) else "CLM said yes less than usual"}
                         for k, c, w in zip(FEATURES, contrib, cal["weights"])]
        towards_scam = sorted((c for c in contributions if c["push"] > 0.3), key=lambda c: -c["push"])
        towards_legit = sorted((c for c in contributions if c["push"] < -0.3), key=lambda c: c["push"])
        calibrated = True
    else:  # fallback: noisy-OR over the raw flag answers
        keep = 1.0
        contributions = []
        for f in RED_FLAGS:
            p = probs.get(f["id"], 0.0)
            keep *= 1 - f["strength"] * p
            contributions.append({"id": f["id"], "label": f["label"], "p": p, "push": f["strength"] * p})
        risk = 1 - keep
        towards_scam = sorted((c for c in contributions if c["p"] >= 0.5), key=lambda c: -c["push"])
        towards_legit = []
        calibrated = False
    decision = "warn" if risk >= WARN_AT else "check" if risk >= CHECK_AT else "ok"
    return {"risk": risk, "decision": decision, "calibrated": calibrated,
            "fired": [_reason(c) for c in towards_scam], "against": [_reason(c) for c in towards_legit],
            "contributions": contributions,
            "calibration_note": (f"calibrated on {cal['n']} labelled listings" if calibrated else
                                 "not calibrated yet: raw CLM percentages are shifted, run tools/calibrate.py")}


def model_entry(ok: bool, probs: dict[str, float] | None, latency_ms: float, server_ms=None,
                model=None, error=None, provider: str | None = None) -> dict:
    """One model's analysis from its raw yes/no probabilities (live or recorded)."""
    entry = {"ok": ok, "error": error, "latency_ms": latency_ms, "server_ms": server_ms, "model": model}
    if ok and probs:
        entry["flags"] = {f["id"]: probs[f["id"]] for f in RED_FLAGS}
        entry["overall"] = probs[OVERALL["id"]]
        entry["combined"] = combine(probs, provider)
    return entry


def assemble(models: dict[str, dict]) -> dict:
    """Combine per-model entries into the response the web page renders."""
    out = {"flags": RED_FLAGS, "overall_question": OVERALL["question"], "models": models,
           "model_order": [m for m in MODELS if m in models]}
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
    """Live: ask the demo's models (in parallel if more than one) and combine each model's answers."""
    results = await client.compare(listing_state(listing), questions(), MODELS)
    return assemble({
        name: model_entry(res.ok, {k: a.value for k, a in res.answers.items()}, res.latency_ms,
                          res.server_ms, res.model, res.error, provider=name)
        for name, res in results.items()
    })


def listing_hash(listing: dict) -> str:
    """Fingerprint of the listing text, so an edited listing never replays an old recording."""
    return hashlib.sha256(listing["text"].encode("utf-8")).hexdigest()[:16]


def load_examples() -> list[dict]:
    with open(DATA, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
