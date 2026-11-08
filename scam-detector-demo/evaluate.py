"""
Offline evaluation of the scam detector: Jev vs CLM on the labelled listings.

    python scam-detector-demo/record.py --providers clm     (first: record each model)
    python scam-detector-demo/record.py --providers jev
    python scam-detector-demo/evaluate.py                    (then: metrics, from the repository root)

It makes NO model calls itself: it reads the recordings in recordings/scam/, the
same files the web app replays. So the numbers on your slide and the replay on
screen come from exactly the same answers.

Writes to scam-detector-demo/results/:
  predictions.csv           one row per listing and model, for your own analysis
  report.md                 the comparison table, calibration bins and fitted weights

What it measures, per model:
  * AUC of the checklist risk and of the one big question (ranking quality, 1.0 = perfect)
  * Brier score of the one big question (lower is better; measures calibration + accuracy)
  * accuracy/precision/recall when "check" or "warn" counts as flagged
  * median and 95th-percentile latency
  * a logistic regression on the 9 flag probabilities, with leave-one-out
    cross-validation, as a learned alternative to the hand-set weights

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

from scam.detector import CHECK_AT, RED_FLAGS, combine, load_examples  # noqa: E402
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


def logistic_regression_loo(X, y):
    """Leave-one-out predictions + weights fitted on all data. Needs scikit-learn."""
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return None, None
    preds = []
    for i in range(len(X)):
        Xtr = [x for j, x in enumerate(X) if j != i]
        ytr = [v for j, v in enumerate(y) if j != i]
        if len(set(ytr)) < 2:
            preds.append(0.5)
            continue
        m = LogisticRegression(C=1.0, max_iter=1000).fit(Xtr, ytr)
        preds.append(float(m.predict_proba([X[i]])[0][1]))
    full = LogisticRegression(C=1.0, max_iter=1000).fit(X, y)
    weights = dict(zip([f["label"] for f in RED_FLAGS], full.coef_[0].tolist()))
    return preds, weights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", nargs="+", default=["jev", "clm"], choices=["jev", "clm"])
    args = ap.parse_args()

    listings = load_examples()
    labels = [1 if x["label"] == "scam" else 0 for x in listings]
    report = ["# Scam detector: Jev vs CLM", "",
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
        flag_p = [[ans[x["id"]]["probs"][f["id"]] for f in RED_FLAGS] for x in ok]
        overall = [ans[x["id"]]["probs"]["overall"] for x in ok]
        combos = [combine(dict(zip([f["id"] for f in RED_FLAGS], fp))) for fp in flag_p]
        risk = [c["risk"] for c in combos]
        flagged = [int(c["decision"] != "ok") for c in combos]
        tp = sum(f and t for f, t in zip(flagged, y))
        fp_ = sum(f and not t for f, t in zip(flagged, y))
        fn = sum((not f) and t for f, t in zip(flagged, y))
        lat = [ans[x["id"]]["latency_ms"] for x in ok]
        lr_preds, lr_weights = logistic_regression_loo(flag_p, y)
        metrics[prov] = {
            "Answered": f"{len(ok)}/{len(listings)}",
            "AUC, checklist risk": auc(risk, y),
            "AUC, one big question": auc(overall, y),
            "AUC, logistic regression (LOO)": auc(lr_preds, y) if lr_preds else None,
            "Brier, one big question (lower = better)": brier(overall, y),
            "Accuracy (flagged vs label)": sum(f == t for f, t in zip(flagged, y)) / len(y),
            "Precision": tp / (tp + fp_) if tp + fp_ else None,
            "Recall (scams caught)": tp / (tp + fn) if tp + fn else None,
            "Median latency (ms)": statistics.median(lat),
            "95th pct latency (ms)": percentile(lat, 0.95),
        }
        for x, c, o in zip(ok, combos, overall):
            rows_csv.append({"provider": prov, "id": x["id"], "label": x["label"], "risk": round(c["risk"], 4),
                             "decision": c["decision"], "overall_p": round(o, 4),
                             **{f["id"]: round(ans[x["id"]]["probs"][f["id"]], 4) for f in RED_FLAGS},
                             "latency_ms": round(ans[x["id"]]["latency_ms"], 1)})
        extra += [f"## {prov}: calibration of the one big question", "",
                  "| Predicted P(scam) | n | mean predicted | actual scam rate |", "|---|---|---|---|"]
        extra += [f"| {b} | {n} | {mp:.2f} | {ar:.2f} |" for b, n, mp, ar in calibration_bins(overall, y)]
        extra.append("")
        if lr_weights:
            extra += [f"## {prov}: learned logistic-regression weights", "",
                      "Positive = pushes towards scam. Compare with the hand-set strengths in scam/detector.py.", "",
                      "| Red flag | weight |", "|---|---|"]
            extra += [f"| {k} | {v:+.2f} |" for k, v in sorted(lr_weights.items(), key=lambda kv: -kv[1])]
            extra.append("")
        misses = [f"{x['id']} ({x['label']}, risk {c['risk']:.2f})" for x, c, t in zip(ok, combos, y)
                  if int(c["decision"] != "ok") != t]
        extra += [f"**{prov} mistakes:** " + (", ".join(misses) or "none"), ""]

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
