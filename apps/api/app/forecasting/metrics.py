"""Binary metrics. Undefined results stay null. They are not stored as zero.

The positive class is direction 1, a strictly rising next close.
A probability of 0.5 or below predicts class 0.
"""

from __future__ import annotations

import math

POSITIVE_CLASS = 1
PROBABILITY_FLOOR = 1e-15
CALIBRATION_MIN = 20


def binary_metrics(labels: list[int], probabilities: list[float]) -> dict:
    if len(labels) != len(probabilities) or not labels:
        return _undefined("NO_OBSERVATIONS")
    if any(label not in (0, 1) for label in labels):
        return _undefined("INVALID_LABEL")
    if any(not math.isfinite(probability) or probability < 0 or probability > 1 for probability in probabilities):
        return _undefined("INVALID_PROBABILITY")
    predicted = [1 if probability > 0.5 else 0 for probability in probabilities]
    tp = sum(1 for label, pred in zip(labels, predicted) if label == 1 and pred == 1)
    tn = sum(1 for label, pred in zip(labels, predicted) if label == 0 and pred == 0)
    fp = sum(1 for label, pred in zip(labels, predicted) if label == 0 and pred == 1)
    fn = sum(1 for label, pred in zip(labels, predicted) if label == 1 and pred == 0)
    positives = tp + fn
    negatives = tn + fp
    predicted_positives = tp + fp
    count = len(labels)
    accuracy = (tp + tn) / count
    true_positive_rate = None if positives == 0 else tp / positives
    true_negative_rate = None if negatives == 0 else tn / negatives
    if true_positive_rate is None or true_negative_rate is None:
        balanced = _metric(None, "UNDEFINED_MISSING_CLASS")
    else:
        balanced = _metric((true_positive_rate + true_negative_rate) / 2, "DEFINED")
    precision = _metric(None, "UNDEFINED_NO_PREDICTED_POSITIVE") if predicted_positives == 0 else _metric(tp / predicted_positives, "DEFINED")
    recall = _metric(None, "UNDEFINED_NO_POSITIVE") if positives == 0 else _metric(tp / positives, "DEFINED")
    if precision["value"] is None or recall["value"] is None or precision["value"] + recall["value"] == 0:
        reason = "UNDEFINED_PRECISION_OR_RECALL" if precision["value"] is None or recall["value"] is None else "UNDEFINED_ZERO_PRECISION_AND_RECALL"
        f1 = _metric(None, reason)
    else:
        f1 = _metric(2 * precision["value"] * recall["value"] / (precision["value"] + recall["value"]), "DEFINED")
    clipped = [min(1 - PROBABILITY_FLOOR, max(PROBABILITY_FLOOR, probability)) for probability in probabilities]
    log_loss = -sum(
        label * math.log(probability) + (1 - label) * math.log(1 - probability)
        for label, probability in zip(labels, clipped)
    ) / count
    brier = sum((probability - label) ** 2 for label, probability in zip(labels, probabilities)) / count
    return {
        "status": "DEFINED",
        "observations": count,
        "positive_class": POSITIVE_CLASS,
        "positive_prevalence": positives / count,
        "accuracy": _metric(accuracy, "DEFINED"),
        "balanced_accuracy": balanced,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "log_loss": _metric(log_loss, "DEFINED_WITH_PROBABILITY_FLOOR"),
        "brier": _metric(brier, "DEFINED"),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "probability_distribution": _distribution(probabilities),
        "calibration": _calibration(labels, probabilities),
        "probabilities_are_calibrated": False,
    }


def _metric(value: float | None, status: str) -> dict:
    return {"value": value, "status": status}


def _undefined(status: str) -> dict:
    empty = _metric(None, status)
    return {
        "status": status,
        "observations": 0,
        "positive_class": POSITIVE_CLASS,
        "positive_prevalence": None,
        "accuracy": empty,
        "balanced_accuracy": empty,
        "precision": empty,
        "recall": empty,
        "f1": empty,
        "log_loss": empty,
        "brier": empty,
        "confusion_matrix": None,
        "probability_distribution": None,
        "calibration": {"status": "NOT_RUN", "bins": None, "probabilities_are_calibrated": False},
        "probabilities_are_calibrated": False,
    }


def _distribution(probabilities: list[float]) -> dict:
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001)
    counts = [0, 0, 0, 0, 0]
    for probability in probabilities:
        for index in range(5):
            if edges[index] <= probability < edges[index + 1]:
                counts[index] += 1
                break
    return {
        "min": min(probabilities),
        "max": max(probabilities),
        "mean": sum(probabilities) / len(probabilities),
        "histogram": [
            {"low": edges[index], "high": 1.0 if index == 4 else edges[index + 1], "count": counts[index]}
            for index in range(5)
        ],
    }


def _calibration(labels: list[int], probabilities: list[float]) -> dict:
    if len(labels) < CALIBRATION_MIN:
        return {
            "status": "INSUFFICIENT_OBSERVATIONS",
            "bins": None,
            "required_observations": CALIBRATION_MIN,
            "probabilities_are_calibrated": False,
        }
    paired = sorted(zip(probabilities, labels), key=lambda item: item[0])
    bin_count = 5
    bins = []
    for index in range(bin_count):
        start = index * len(paired) // bin_count
        stop = (index + 1) * len(paired) // bin_count
        chunk = paired[start:stop]
        if not chunk:
            continue
        probs = [item[0] for item in chunk]
        ys = [item[1] for item in chunk]
        bins.append(
            {
                "count": len(chunk),
                "mean_predicted": sum(probs) / len(probs),
                "fraction_positive": sum(ys) / len(ys),
            }
        )
    return {"status": "COMPUTED", "bins": bins, "probabilities_are_calibrated": False}
