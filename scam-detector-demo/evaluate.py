"""
Offline evaluation of the scam detector on the labelled listings (CLM by default; SCAM_MODELS to compare).

    python scam-detector-demo/record.py                      (first: record the demo's models)
    python scam-detector-demo/evaluate.py                    (then: metrics, from the repository root)

It makes NO model calls itself: it reads the recordings in recordings/scam/, the
same files the web app replays. So the numbers on your slide and the replay on
screen come from exactly the same answers.

Writes to scam-detector-demo/results/:
  predictions.csv           one row per listing and model, for your own analysis
  report.md                 the comparison table, calibration bins and fitted weights

What it measures, per model:
  * AUC (ranking quality, 1.0 = perfect) and Brier score (lower is better),
    raw vs calibrated. Calibrated numbers are leave-one-out: each listing is
    scored by a calibration that never saw it, so they are not flattered.
  * accuracy/precision/recall when "check" or "warn" counts as flagged
  * reliability tables (predicted vs actual scam rate) and the calibration weights
  * median and 95th-percentile latency

Note: the dataset is small (30 synthetic listings), so treat the numbers as a
classroom illustration, not a benchmark. Add real listings to data/listings.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from scam.detector import CHECK_AT, FEATURES, LABELS, MODELS, RED_FLAGS, WARN_AT, combine, load_calibration, load_examples  # noqa: E402
from system_one.calibration import loo_predict  # noqa: E402
from scam.recorded import latest_calls  # noqa: E402

RESULTS = HERE / "results"


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Probability that a random scam scores higher than a random legit listing."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def brier(probs: list[float], labels: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(labels)


def calibration_bins(probs, labels, edges=(0, 0.2, 0.4, 0.6, 0.8, 1.0001)):
    rows = []
    for lo, hi in zip(edges, edges[1:]):
        idx = [i for i, p in enumerate(probs) if lo <= p < hi]
        if idx:
            rows.append((f"{lo:.1f}–{min(hi, 1):.1f}", len(idx),
                         sum(probs[i] for i in idx) / len(idx), sum(labels[i] for i in idx) / len(idx)))
    return rows


def percentile(xs, q):
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, round(q * (len(xs) - 1))))
    return xs[k]


def recorded_answers(provider: str) -> tuple[dict, list[dict]]:
    """{listing_id: {"ok", "error", "latency_ms", "probs"}} from the latest recordings, + session info."""
    by_id = latest_calls().get(provider, {})
    out, sessions = {}, {}
    for lid, hit in by_id.items():
        c = hit["call"]
        out[lid] = {"ok": bool(c.get("ok")), "error": c.get("error"), "latency_ms": c.get("latency_ms", 0.0),
                    "probs": {k: a["value"] for k, a in (c.get("answers") or {}).items()}}
        sessions[hit["meta"]["session_id"]] = hit["meta"]
    return out, list(sessions.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", nargs="+", default=MODELS, choices=["jev", "clm"])
    args = ap.parse_args()

    listings = load_examples()
    labels = [1 if x["label"] == "scam" else 0 for x in listings]
    report = ["# Scam detector: evaluation (" + ", ".join(args.providers) + ")", "",
              f"{len(listings)} listings ({sum(labels)} scams). Flagged = decision 'check' or 'warn' "
              f"(risk ≥ {CHECK_AT}).", ""]
    metrics: dict[str, dict] = {}
    rows_csv = []
    extra = []

    for prov in args.providers:
        ans, sessions = recorded_answers(prov)
        ok = [x for x in listings if x["id"] in ans and ans[x["id"]]["ok"]]
        if not ok:
            print(f"  {prov}: no recorded answers. Run: python scam-detector-demo/record.py --providers {prov}")
            continue
        for m in sessions:
            print(f"  {prov}: using {m['file']} (recorded {m['recorded_at']}, {m['where'] or 'location not given'})")
            report.append(f"- {prov}: `{m['file']}`, recorded {m['recorded_at']}"
                          f"{', ' + m['where'] if m['where'] else ''}, network ping {m['ping_ms']} ms")
        y = [1 if x["label"] == "scam" else 0 for x in ok]
        rows = [[ans[x["id"]]["probs"][k] for k in FEATURES] for x in ok]
        overall = [r[FEATURES.index("overall")] for r in rows]
        raw = [combine(dict(zip(FEATURES, r)), None)["risk"] for r in rows]   # uncalibrated noisy-OR
        # Honest number: each listing is scored by a calibration fitted WITHOUT it.
        loo = loo_predict(rows, y, l2=1.0) if len(set(y)) == 2 else [0.5] * len(y)
        cal = load_calibration(prov)
        flagged = [int(p >= CHECK_AT) for p in loo]
        tp = sum(f and t for f, t in zip(flagged, y))
        fp_ = sum(f and not t for f, t in zip(flagged, y))
        fn = sum((not f) and t for f, t in zip(flagged, y))
        lat = [ans[x["id"]]["latency_ms"] for x in ok]
        metrics[prov] = {
            "Answered": f"{len(ok)}/{len(listings)}",
            "AUC, raw checklist (no calibration)": auc(raw, y),
            "AUC, raw one big question": auc(overall, y),
            "AUC, calibrated (leave-one-out)": auc(loo, y),
            "Brier, raw one big question (lower = better)": brier(overall, y),
            "Brier, calibrated (leave-one-out)": brier(loo, y),
            "Accuracy, calibrated (flag at check)": sum(f == t for f, t in zip(flagged, y)) / len(y),
            "Precision": tp / (tp + fp_) if tp + fp_ else None,
            "Recall (scams caught)": tp / (tp + fn) if tp + fn else None,
            "Median latency (ms)": statistics.median(lat),
            "95th pct latency (ms)": percentile(lat, 0.95),
        }
        for x, r, o, rp, lp in zip(ok, rows, overall, raw, loo):
            rows_csv.append({"provider": prov, "id": x["id"], "label": x["label"],
                             "raw_risk": round(rp, 4), "calibrated_loo": round(lp, 4),
                             "decision": "warn" if lp >= WARN_AT else "check" if lp >= CHECK_AT else "ok",
                             **{k: round(v, 4) for k, v in zip(FEATURES, r)},
                             "latency_ms": round(ans[x["id"]]["latency_ms"], 1)})
        for name, probs in (("raw one big question", overall), ("calibrated (leave-one-out)", loo)):
            extra += [f"## {prov}: reliability, {name}", "",
                      "If the model is calibrated, 'mean predicted' matches 'actual scam rate'.", "",
                      "| Predicted P(scam) | n | mean predicted | actual scam rate |", "|---|---|---|---|"]
            extra += [f"| {b} | {n} | {mp:.2f} | {ar:.2f} |" for b, n, mp, ar in calibration_bins(probs, y)]
            extra.append("")
        if cal:
            extra += [f"## {prov}: calibration weights (data/calibration_{prov}.json)", "",
                      "Per standardised CLM score. Positive = a higher yes-score pushes towards scam.", "",
                      "| Question | weight |", "|---|---|"]
            extra += [f"| {LABELS[k]} | {w:+.2f} |" for k, w in
                      sorted(zip(cal["features"] if "features" in cal else FEATURES, cal["weights"]), key=lambda kv: -kv[1])]
            extra.append("")
        else:
            extra += [f"_{prov}: no calibration file yet. Run `python tools/calibrate.py`._", ""]
        misses = [f"{x['id']} ({x['label']}, {p:.2f})" for x, p, t in zip(ok, loo, y) if int(p >= CHECK_AT) != t]
        extra += [f"**{prov} mistakes (calibrated, leave-one-out):** " + (", ".join(misses) or "none"), ""]

    def fmt(v):
        if v is None:
            return "–"
        if isinstance(v, str):
            return v
        return f"{v:.0f}" if v > 2 else f"{v:.2f}"

    table = ["| Metric | " + " | ".join(metrics) + " |", "|---|" + "---|" * len(metrics)] if metrics else \
        ["No recordings found. Record first: python scam-detector-demo/record.py --providers clm"]
    if metrics:
        for key in next(iter(metrics.values())):
            table.append(f"| {key} | " + " | ".join(fmt(metrics[p].get(key)) for p in metrics) + " |")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "report.md").write_text("\n".join(report + [""] + table + [""] + extra), encoding="utf-8")
    if rows_csv:
        with open(RESULTS / "predictions.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows_csv[0]))
            w.writeheader()
            w.writerows(rows_csv)
    print("\n".join(table))
    print(f"\nWrote {RESULTS / 'report.md'}")


if __name__ == "__main__":
    main()
