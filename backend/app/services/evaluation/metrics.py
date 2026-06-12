"""Pure-function evaluation metrics for football match outcome predictions.

All functions accept:
    predictions: list[dict]  — each dict has home_win, draw, away_win (float, sum ≈ 1)
    actuals:     list[str]   — each str is "home_win" | "draw" | "away_win"
"""

from __future__ import annotations

import math
from typing import Any

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_proba(pred: dict) -> tuple[float, float, float]:
    """Extract (home_win, draw, away_win) and normalize to sum = 1."""
    h = float(pred.get("home_win", 1 / 3))
    d = float(pred.get("draw",     1 / 3))
    a = float(pred.get("away_win", 1 / 3))
    total = h + d + a
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return h / total, d / total, a / total


def _to_onehot(actual: str) -> tuple[float, float, float]:
    return (
        1.0 if actual == "home_win" else 0.0,
        1.0 if actual == "draw"     else 0.0,
        1.0 if actual == "away_win" else 0.0,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def brier_score(predictions: list[dict], actuals: list[str]) -> float:
    """Multiclass Brier score, normalized to [0, 1].

    BS = mean_i [ (1/2) * sum_k (p_k - y_k)^2 ]

    Range: 0 = perfect, 1 = worst possible.
    """
    if not predictions:
        return 0.0
    total = 0.0
    for pred, actual in zip(predictions, actuals):
        ph, pd, pa = _to_proba(pred)
        yh, yd, ya = _to_onehot(actual)
        total += (ph - yh) ** 2 + (pd - yd) ** 2 + (pa - ya) ** 2
    return total / (2.0 * len(predictions))


def log_loss(predictions: list[dict], actuals: list[str]) -> float:
    """Multi-class cross-entropy (negative log-likelihood).

    Range: 0 (perfect) to ∞. Uniform predictor ≈ log(3) ≈ 1.099.
    """
    if not predictions:
        return 0.0
    total = 0.0
    for pred, actual in zip(predictions, actuals):
        ph, pd, pa = _to_proba(pred)
        p_map = {"home_win": ph, "draw": pd, "away_win": pa}
        p_correct = p_map.get(actual, _EPS)
        total += -math.log(max(p_correct, _EPS))
    return total / len(predictions)


def ranked_probability_score(predictions: list[dict], actuals: list[str]) -> float:
    """Ranked Probability Score (ordered Brier score).

    Outcomes are ordered: home_win < draw < away_win.
    RPS = (1/2) * [ (F1 - O1)^2 + (F1+F2 - O1-O2)^2 ]

    Range: 0 (perfect) to 1 (worst).
    """
    if not predictions:
        return 0.0
    total = 0.0
    for pred, actual in zip(predictions, actuals):
        ph, pd, pa = _to_proba(pred)
        yh, yd, ya = _to_onehot(actual)
        # Cumulative
        f1, f2 = ph, ph + pd
        o1, o2 = yh, yh + yd
        total += (f1 - o1) ** 2 + (f2 - o2) ** 2
    return total / (2.0 * len(predictions))


def accuracy(predictions: list[dict], actuals: list[str]) -> float:
    """Fraction of correctly predicted outcomes (argmax class).

    Range: 0 to 1.
    """
    if not predictions:
        return 0.0
    correct = 0
    for pred, actual in zip(predictions, actuals):
        ph, pd, pa = _to_proba(pred)
        probs = {"home_win": ph, "draw": pd, "away_win": pa}
        predicted = max(probs, key=lambda k: probs[k])
        if predicted == actual:
            correct += 1
    return correct / len(predictions)


def calibration_data(
    predictions: list[dict],
    actuals: list[str],
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    """Calibration data for the home_win probability.

    Returns n_bins dicts, each with:
        bin_center:     float  — midpoint of the predicted probability bin
        predicted_freq: float  — mean predicted p(home_win) in this bin
        observed_freq:  float  — fraction of actual home wins in this bin
        count:          int    — number of samples in this bin
    """
    bins: list[dict[str, Any]] = [
        {
            "bin_center":     (i + 0.5) / n_bins,
            "predicted_sum":  0.0,
            "observed_count": 0,
            "count":          0,
        }
        for i in range(n_bins)
    ]

    for pred, actual in zip(predictions, actuals):
        ph, _, _ = _to_proba(pred)
        idx = min(int(ph * n_bins), n_bins - 1)
        bins[idx]["predicted_sum"]  += ph
        bins[idx]["count"]          += 1
        if actual == "home_win":
            bins[idx]["observed_count"] += 1

    result: list[dict[str, Any]] = []
    for b in bins:
        n = b["count"]
        result.append({
            "bin_center":     b["bin_center"],
            "predicted_freq": b["predicted_sum"] / n if n > 0 else b["bin_center"],
            "observed_freq":  b["observed_count"] / n if n > 0 else 0.0,
            "count":          n,
        })
    return result
