"""Metrics both model trainers report, defined once.

The plan (§E.4) requires calibration, Brier, ROC-AUC, PR-AUC and
precision/recall at a stated review capacity — the last one because a
dispatcher reviews a queue, not a probability. "Capacity" here means: if a
reviewer can look at the riskiest K% of open tickets, how many of the tickets
that actually breached are in that slice.
"""
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

#: Review capacities reported for every risk model. Stated up front so the
#: threshold is not chosen after seeing which one flatters the model.
REVIEW_CAPACITIES = (0.10, 0.20, 0.30)
#: Equal-width reliability bins. Ten is the convention and it keeps roughly 350
#: validation tickets per bin at this dataset's size.
RELIABILITY_BINS = 10


def reliability_table(y_true, probabilities, bins=RELIABILITY_BINS):
    """Predicted probability against observed frequency, bin by bin."""
    y_true = np.asarray(y_true, dtype=float)
    probabilities = np.asarray(probabilities, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(probabilities, edges[1:-1], right=False), 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = index == b
        if not mask.any():
            continue
        rows.append({
            "bin_low": float(edges[b]),
            "bin_high": float(edges[b + 1]),
            "n": int(mask.sum()),
            "mean_predicted": float(probabilities[mask].mean()),
            "observed_rate": float(y_true[mask].mean()),
        })
    return rows


def expected_calibration_error(y_true, probabilities, bins=RELIABILITY_BINS):
    """Weighted mean gap between predicted probability and observed rate."""
    table = reliability_table(y_true, probabilities, bins=bins)
    total = sum(row["n"] for row in table)
    if not total:
        return float("nan")
    return float(sum(
        row["n"] / total * abs(row["mean_predicted"] - row["observed_rate"])
        for row in table
    ))


def precision_recall_at_capacity(y_true, probabilities, capacity):
    """Score the top ``capacity`` fraction of tickets, ranked by risk."""
    y_true = np.asarray(y_true, dtype=bool)
    probabilities = np.asarray(probabilities, dtype=float)
    n = len(y_true)
    k = max(1, int(round(n * capacity)))
    # Rank descending; ties broken by position, which is chronological order.
    top = np.argsort(-probabilities, kind="mergesort")[:k]
    caught = int(y_true[top].sum())
    breaches = int(y_true.sum())
    return {
        "capacity": float(capacity),
        "reviewed": int(k),
        "precision": float(caught / k),
        "recall": float(caught / breaches) if breaches else float("nan"),
    }


def classification_metrics(y_true, probabilities, label):
    """Everything the plan requires, for one split, under one name."""
    y_true = np.asarray(y_true, dtype=bool)
    probabilities = np.asarray(probabilities, dtype=float)
    return {
        "split": label,
        "n": int(len(y_true)),
        "base_rate": float(y_true.mean()),
        "mean_predicted": float(probabilities.mean()),
        "brier": float(brier_score_loss(y_true, probabilities)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "expected_calibration_error": expected_calibration_error(y_true, probabilities),
        "review_capacity": [
            precision_recall_at_capacity(y_true, probabilities, c)
            for c in REVIEW_CAPACITIES
        ],
        "reliability": reliability_table(y_true, probabilities),
    }


def regression_metrics(y_true_minutes, predicted_minutes, label):
    """Median absolute error first: the duration target has a long right tail,
    so a mean-based error is dominated by a handful of month-long incidents."""
    y = np.asarray(y_true_minutes, dtype=float)
    p = np.asarray(predicted_minutes, dtype=float)
    error = np.abs(y - p)
    return {
        "split": label,
        "n": int(len(y)),
        "median_absolute_error_minutes": float(np.median(error)),
        "mean_absolute_error_minutes": float(error.mean()),
        "p90_absolute_error_minutes": float(np.quantile(error, 0.90)),
        "median_actual_minutes": float(np.median(y)),
        "median_predicted_minutes": float(np.median(p)),
    }
