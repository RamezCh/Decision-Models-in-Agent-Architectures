"""
Calibration: turn CLM's raw scores into probabilities you can put a threshold on.

Why: CLM ranks well but its raw numbers are shifted per question. In our tests,
"is this a scam?" averaged 96% on scams and 93% on legit listings: the right
order, useless as a percentage. Jev claims to be calibrated out of the box (its
training method is built for that); for CLM we calibrate on a few labelled examples.

Two tools, both plain logistic regression (numpy only, no scikit-learn needed):
  * platt(p, y)          one question -> calibrated probability (2 parameters)
  * fit_logistic(X, y)   several answers combined -> one calibrated probability,
                         with a readable weight per answer

Both work on log-odds, logit(p) = log(p / (1 - p)), which spreads out scores that
are squeezed near 0 or 1 (0.988 vs 0.9998 becomes 4.4 vs 8.5).

loo_predict() gives leave-one-out predictions: each example is scored by a model
fitted WITHOUT it. Use those to report honest metrics on a small dataset.
"""

from __future__ import annotations

import math

import numpy as np

EPS = 1e-4


def logit(p: float) -> float:
    p = min(1 - EPS, max(EPS, float(p)))
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def fit_logistic(X, y, l2: float = 1.0, iters: int = 100):
    """L2-regularised logistic regression by Newton's method.

    X: (n, k) features (already standardised), y: (n,) 0/1. Returns (weights, bias).
    The bias is not regularised. l2 keeps weights small on tiny datasets.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    A = np.hstack([X, np.ones((n, 1))])
    w = np.zeros(k + 1)
    reg = np.full(k + 1, l2)
    reg[-1] = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(A @ w, -30, 30)))
        grad = A.T @ (p - y) + reg * w
        H = (A * (p * (1 - p))[:, None]).T @ A + np.diag(reg) + 1e-9 * np.eye(k + 1)
        step = np.linalg.solve(H, grad)
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w[:-1].tolist(), float(w[-1])


def standardise(X):
    X = np.asarray(X, dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    return ((X - mean) / std), mean.tolist(), std.tolist()


def fit_combined(rows: list[list[float]], y: list[int], l2: float = 1.0) -> dict:
    """Probabilities per answer (rows) -> calibration dict for predict_combined()."""
    X = np.array([[logit(p) for p in r] for r in rows])
    Z, mean, std = standardise(X)
    w, b = fit_logistic(Z, y, l2)
    return {"kind": "logistic", "mean": mean, "std": std, "weights": w, "bias": b, "l2": l2}


def predict_combined(cal: dict, probs: list[float]) -> tuple[float, list[float]]:
    """-> (calibrated probability, contribution of each answer in log-odds)."""
    z = [(logit(p) - m) / s for p, m, s in zip(probs, cal["mean"], cal["std"])]
    contrib = [w * zi for w, zi in zip(cal["weights"], z)]
    return sigmoid(cal["bias"] + sum(contrib)), contrib


def platt(p: list[float], y: list[int], l2: float = 0.1) -> dict:
    """One question: calibrated = sigmoid(a * logit(p) + b), fitted on standardised logits."""
    return fit_combined([[v] for v in p], y, l2)


def predict_platt(cal: dict, p: float) -> float:
    return predict_combined(cal, [p])[0]


def loo_predict(rows: list[list[float]], y: list[int], l2: float = 1.0) -> list[float]:
    """Leave-one-out calibrated predictions (each row scored by a fit without it)."""
    out = []
    for i in range(len(rows)):
        tr_rows = rows[:i] + rows[i + 1:]
        tr_y = y[:i] + y[i + 1:]
        if len(set(tr_y)) < 2:
            out.append(0.5)
            continue
        out.append(predict_combined(fit_combined(tr_rows, tr_y, l2), rows[i])[0])
    return out


def auc(scores: list[float], labels: list[int]) -> float | None:
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def brier(probs: list[float], labels: list[int]) -> float:
    return sum((p - l) ** 2 for p, l in zip(probs, labels)) / len(labels)
