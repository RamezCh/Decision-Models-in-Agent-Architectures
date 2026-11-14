"""
Calibrate CLM's raw scores on the labelled examples, from the recordings.

    python tools/calibrate.py                                     after recording (from the repository root)
    python tools/calibrate.py --scam-from tools/clm_diagnosis.json  scam check only, from a diagnosis run

Writes, per model:
  scam-detector-demo/data/calibration_<model>.json    combines the 10 answers into one calibrated risk
  beat-the-guard-demo/data/calibration_<model>.json   maps the raw "is this an attack?" score to a probability

Why: CLM ranks well, but its raw percentages are shifted per question (e.g. "is it
a scam?" averaged 96% on scams and 93% on legit listings). A small logistic
regression on the labelled examples turns them into probabilities you can put a
threshold on. The recordings keep the raw answers, so re-running this never
needs a new recording.

Honesty check: the numbers it prints are LEAVE-ONE-OUT. Each example is scored by
a calibration fitted without it, so they estimate how it does on new data. With
30 listings and 25 messages, treat them as a classroom illustration.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "scam-detector-demo", "beat-the-guard-demo"):
    sys.path.insert(0, str(ROOT / sub))

from system_one.calibration import auc, brier, fit_combined, loo_predict  # noqa: E402


def report(name: str, raw: list[float], loo: list[float], y: list[int]):
    print(f"  {name}")
    print(f"    ranking (AUC):        raw {auc(raw, y):.2f}   calibrated, leave-one-out {auc(loo, y):.2f}")
    print(f"    Brier (lower=better): raw {brier(raw, y):.3f}  calibrated, leave-one-out {brier(loo, y):.3f}")
    pos = [p for p, l in zip(loo, y) if l]
    neg = [p for p, l in zip(loo, y) if not l]
    print(f"    average calibrated P: positives {sum(pos) / len(pos):.2f}, negatives {sum(neg) / len(neg):.2f}")


def calibrate_scam(source: str | None):
    from scam.detector import FEATURES, LABELS, MODELS, QUESTIONS_VERSION, calibration_path, load_examples
    labels = {x["id"]: int(x["label"] == "scam") for x in load_examples()}
    datasets = {}
    if source:
        d = json.loads(Path(source).read_text(encoding="utf-8"))
        datasets["clm"] = ({lid: p for lid, p in d["scam"]["described"]["probs"].items()}, f"diagnosis run {d.get('when')}")
    else:
        from scam.recorded import latest_calls
        for prov, by_id in latest_calls().items():
            probs = {lid: {k: a["value"] for k, a in h["call"]["answers"].items()}
                     for lid, h in by_id.items() if h["call"].get("ok")}
            sessions = sorted({h["meta"]["file"] for h in by_id.values()})
            datasets[prov] = (probs, ", ".join(sessions))
    if not datasets:
        print("Scam check: no recordings with the current questions. Run: python scam-detector-demo/record.py")
        return
    print("\nSCAM CHECK")
    for prov, (probs, source_name) in datasets.items():
        if prov not in MODELS:
            continue
        ids = [i for i in probs if i in labels and all(k in probs[i] for k in FEATURES)]
        rows = [[probs[i][k] for k in FEATURES] for i in ids]
        y = [labels[i] for i in ids]
        if len(set(y)) < 2 or len(ids) < 10:
            print(f"  {prov}: only {len(ids)} usable listings, skipping")
            continue
        cal = fit_combined(rows, y, l2=1.0)
        loo = loo_predict(rows, y, l2=1.0)
        report(f"{prov}: {len(ids)} listings, combined risk from {len(FEATURES)} answers", [r[-1] for r in rows], loo, y)
        weights = sorted(zip(FEATURES, cal["weights"]), key=lambda t: -abs(t[1]))
        print("    weights (positive = points to scam): " +
              ", ".join(f"{LABELS[k]} {w:+.2f}" for k, w in weights[:5]) + ", ...")
        cal.update(questions_version=QUESTIONS_VERSION, features=FEATURES, n=len(ids), model=prov,
                   fitted_on=source_name, created=time.strftime("%Y-%m-%d %H:%M"),
                   loo_auc=auc(loo, y), loo_brier=brier(loo, y))
        calibration_path(prov).write_text(json.dumps(cal, indent=2), encoding="utf-8")
        print(f"    saved {calibration_path(prov).relative_to(ROOT)}")


def calibrate_guard():
    from guard.game import MODELS, QUESTIONS_VERSION, calibration_path, load_attacks
    from guard.recorded import latest
    labels = {a["id"]: int(a["attack"]) for a in load_attacks()}
    rec = latest()
    if not rec:
        print("\nBeat the guard: no recordings with the current questions. Run: python beat-the-guard-demo/record.py")
        return
    print("\nBEAT THE GUARD (message check)")
    for prov, by_id in rec.items():
        if prov not in MODELS:
            continue
        ids = [i for i, h in by_id.items() if h["call"].get("ok") and i in labels]
        raw = [by_id[i]["call"]["answers"]["attack"]["value"] for i in ids]
        y = [labels[i] for i in ids]
        if len(set(y)) < 2 or len(ids) < 8 or min(sum(y), len(y) - sum(y)) < 2:
            print(f"  {prov}: only {len(ids)} usable messages, skipping")
            continue
        rows = [[p] for p in raw]
        cal = fit_combined(rows, y, l2=0.1)
        loo = loo_predict(rows, y, l2=0.1)
        report(f"{prov}: {len(ids)} messages ({sum(y)} attacks)", raw, loo, y)
        cal.update(questions_version=QUESTIONS_VERSION, n=len(ids), model=prov,
                   fitted_on=", ".join(sorted({h["meta"]["file"] for h in by_id.values()})),
                   created=time.strftime("%Y-%m-%d %H:%M"), loo_auc=auc(loo, y), loo_brier=brier(loo, y))
        calibration_path(prov).write_text(json.dumps(cal, indent=2), encoding="utf-8")
        print(f"    saved {calibration_path(prov).relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description="Calibrate CLM on the labelled examples")
    ap.add_argument("--scam-from", help="fit the scam check from a diagnose_clm.py result instead of recordings")
    ap.add_argument("--only", choices=["scam", "guard"])
    a = ap.parse_args()
    if a.only in (None, "scam"):
        calibrate_scam(a.scam_from)
    if a.only in (None, "guard") and not a.scam_from:
        calibrate_guard()
    print("\nRestart the web app (or just reload the page) to use the new calibration.")


if __name__ == "__main__":
    main()
