"""
Draw the charts in docs/img/ from a real CLM diagnosis run.

    python tools/diagnose_clm.py          (needs the port-forward to CLM; writes tools/clm_diagnosis.json)
    python tools/make_doc_figures.py      (offline; needs matplotlib)

Every number in the charts comes from tools/clm_diagnosis.json, so re-running
both scripts after a model or question change refreshes the docs.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "scam-detector-demo", "beat-the-guard-demo", "rubric-cube-demo"):
    sys.path.insert(0, str(ROOT / sub))

from system_one.calibration import auc, brier, fit_combined, loo_predict  # noqa: E402

OUT = ROOT / "docs" / "img"

# Reference palette (validated: blue/orange pass CVD and contrast checks on the light surface)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
SCAM, LEGIT = "#2a78d6", "#eb6834"
CHANCE = "#8a8984"

plt.rcParams.update({
    "hatch.linewidth": 1.2, "hatch.color": "#fcfcfb",
    "font.family": ["Inter", "DejaVu Sans"], "font.weight": "normal", "font.size": 11, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": False,
    "savefig.facecolor": SURFACE, "savefig.dpi": 200,
})


def title(ax, main, sub=None, legend_room=False):
    ax.set_title(main, loc="left", fontsize=13.5, fontweight="bold", color=INK, pad=(50 if legend_room else 26) if sub else 10)
    if sub:
        ax.text(0, 1.11 if legend_room else 1.02, sub, transform=ax.transAxes, fontsize=10.5, color=INK2, va="bottom")


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print("wrote", (OUT / name).relative_to(ROOT))


def wording_auc(d):
    """Same 30 listings, four ways of asking. AUC: 0.5 = coin flip, 1.0 = perfect ranking."""
    variants = [("current", "Statements,\nno descriptions"), ("question", "Phrased as\nquestions"),
                ("raw", "No trained heads\n(clm-raw)"), ("described", "Yes/no\ndescriptions")]
    series = [("overall_auc", "One big question", SCAM, None), ("risk_auc", "Checklist of 9 red flags", LEGIT, "///")]
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    h = 0.36
    for i, (v, _) in enumerate(variants):
        for j, (key, _, col, hatch) in enumerate(series):
            val = d["scam"][v][key]
            y = i + (j - 0.5) * (h + 0.04)
            ax.barh(y, val, height=h, color=col, edgecolor=SURFACE, linewidth=2, hatch=hatch)
            ax.text(val + 0.012, y, f"{val:.2f}", va="center", fontsize=10, color=INK)
    ax.axvline(0.5, color=CHANCE, lw=1.2, ls=(0, (4, 3)))
    ax.text(0.505, -0.62, "coin flip", ha="left", fontsize=9.5, color=INK2)
    ax.set_yticks(range(len(variants)), [lab for _, lab in variants])
    ax.set_xlim(0, 1.08)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("AUC: chance a random scam scores above a random legit listing")
    ax.tick_params(axis="y", length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, facecolor=c, edgecolor=SURFACE, hatch=hh) for _, _, c, hh in series]
    ax.legend(handles, [lab for _, lab, _, _ in series], loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2,
              frameon=False, fontsize=10, handlelength=1.2)
    ax.set_ylim(len(variants) - 0.45, -0.75)
    title(ax, "How you ask matters more than the model",
          "Scam check, 30 labelled listings, same CLM-8B, four ways of writing the questions", legend_room=True)
    save(fig, "wording_auc.png")


def strip(ax, probs, y, label_y):
    rng = random.Random(3)
    for cls, col, marker, row in ((1, SCAM, "o", 1), (0, LEGIT, "D", 0)):
        xs = [p for p, t in zip(probs, y) if t == cls]
        ys = [row + rng.uniform(-0.17, 0.17) for _ in xs]
        ax.scatter(xs, ys, s=46, color=col, marker=marker, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.set_yticks([0, 1], ["legit", "scam"] if label_y else ["", ""])
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlim(-0.03, 1.03)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", length=0)
    for x in (0.25, 0.5, 0.75):
        ax.axvline(x, color=GRID, lw=0.8, zorder=0)


def raw_vs_calibrated(d, features):
    probs = d["scam"]["described"]["probs"]
    from scam.detector import load_examples
    labels = {x["id"]: int(x["label"] == "scam") for x in load_examples()}
    ids = [i for i in probs if i in labels]
    y = [labels[i] for i in ids]
    raw = [probs[i]["overall"] for i in ids]
    loo = loo_predict([[probs[i][k] for k in features] for i in ids], y, l2=1.0)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    strip(axes[0], raw, y, True)
    strip(axes[1], loo, y, False)
    for ax, name, p in ((axes[0], "Raw CLM answer to “is this a scam?”", raw),
                        (axes[1], "Calibrated, all 10 answers combined", loo)):
        ax.set_title(name, loc="left", fontsize=11.5, color=INK, pad=6)
        ax.set_xlabel(f"P(scam)   ·   AUC {auc(p, y):.2f}   ·   Brier {brier(p, y):.3f}")
    fig.suptitle("Calibration turns a good ranking into honest percentages", x=0.065, y=1.09,
                 ha="left", fontsize=13.5, fontweight="bold")
    fig.text(0.065, 0.985, "Each dot is one listing. Calibrated values are leave-one-out: "
             "each listing is scored by a fit that never saw it. Lower Brier = better.",
             fontsize=10.5, color=INK2, ha="left")
    save(fig, "raw_vs_calibrated.png")
    return fit_combined([[probs[i][k] for k in features] for i in ids], y, l2=1.0)


def weights_chart(cal, features, labels):
    pairs = sorted(zip(features, cal["weights"]), key=lambda t: t[1])
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for i, (k, w) in enumerate(pairs):
        ax.barh(i, w, height=0.62, color=SCAM if w > 0 else LEGIT, edgecolor=SURFACE, linewidth=2)
        ax.text(w + (0.03 if w >= 0 else -0.03), i, f"{w:+.2f}", va="center",
                ha="left" if w >= 0 else "right", fontsize=10)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(range(len(pairs)), [labels[k] for k, _ in pairs])
    ax.tick_params(axis="y", length=0)
    lim = max(abs(w) for _, w in pairs) + 0.35
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("← a higher yes-score points to legit          a higher yes-score points to scam →")
    title(ax, "What the calibration learned to trust",
          "Weight per question (standardised log-odds), fitted on the 30 labelled listings")
    save(fig, "calibration_weights.png")


def guard_scores(d):
    att = d["guard"]["described"]["attack"]
    harmless = {"a01", "a02"}
    ids = sorted(att)
    fig, ax = plt.subplots(figsize=(8.4, 2.9))
    rng = random.Random(1)
    for i in ids:
        is_h = i in harmless
        ax.scatter(att[i], (0 if is_h else 1) + rng.uniform(-0.15, 0.15), s=60,
                   color=LEGIT if is_h else SCAM, marker="D" if is_h else "o",
                   edgecolor=SURFACE, linewidth=1.5, zorder=3)
    ax.set_yticks([0, 1], ["harmless", "attack"])
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlim(0.985, 1.0005)
    ax.set_xticks([0.985, 0.99, 0.995, 1.0], ["98.5%", "99%", "99.5%", "100%"])
    ax.tick_params(axis="y", length=0)
    ax.set_xlabel(f"raw P(attack)   ·   AUC {d['guard']['described']['attack_auc']:.2f}   ·   "
                  "every message is above any sensible threshold")
    title(ax, "Raw guard scores: right order, useless scale",
          "Beat the guard, 12 messages (note the zoomed axis: 98.5% to 100%)")
    save(fig, "guard_raw_scores.png")


def cube_chart(d):
    from_clm = d["cube"]["top1_optimal"]
    # the same 21 positions diagnose_clm.py used: expected hit rate of a uniformly random move
    from agents.players import legal_moves
    from cube.oracle import evaluate_moves
    from cube.scrambler import scramble_exact
    shares = []
    for level in (1, 2, 3):
        for seed in range(1, 8):
            state, _ = scramble_exact(level, seed=seed)
            legal = legal_moves(None)
            shares.append(len(evaluate_moves(state, legal)["optimal"]) / len(legal))
    chance = sum(shares) / len(shares)
    fig, ax = plt.subplots(figsize=(7.4, 2.4))
    for i, (lab, v) in enumerate((("CLM-8B's top move", from_clm), ("Random legal move", chance))):
        ax.barh(i, v, height=0.55, color=SCAM if i == 0 else CHANCE, edgecolor=SURFACE, linewidth=2)
        ax.text(v + 0.003, i, f"{v:.1%}", va="center", fontsize=10.5)
    ax.set_yticks([0, 1], ["CLM-8B's top move", "Random legal move"])
    ax.tick_params(axis="y", length=0)
    ax.invert_yaxis()
    ax.set_xlim(0, 0.12)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    ax.set_xlabel(f"share of positions where the chosen move was optimal  ·  "
                  f"median rank of the best move: {d['cube']['median_rank']:g} of 18")
    title(ax, "The cube is a real limit, not a prompt problem",
          "21 positions, 1 to 3 moves from solved, 18 possible moves: CLM does no better than chance")
    save(fig, "cube_limits.png")


def main():
    src = ROOT / "tools" / "clm_diagnosis.json"
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    d = json.loads(src.read_text(encoding="utf-8"))
    from scam.detector import FEATURES, LABELS
    wording_auc(d)
    cal = raw_vs_calibrated(d, FEATURES)
    weights_chart(cal, FEATURES, LABELS)
    guard_scores(d)
    cube_chart(d)


if __name__ == "__main__":
    main()
