"""Majority class, last-return sign, and L2 logistic regression.

These functions are numeric research primitives. They fit rows that have
already passed a dataset boundary. They do not accept a sealed dataset and
are not called by an API route. Production training enters through
`run_experiment` and `run_walk_forward`, which check dataset lineage before
these functions run.

Scalers and probability maps are fit on the training rows only. Logistic
regression uses Newton steps on standardized features and keeps a fit only
when the step converges. A one-class training set does not receive invented
probabilities.

`last_return_sign` is the persistence baseline: its hard class is the sign of
the last completed one-bar return, `ret_1`.
"""

from __future__ import annotations

import math

from app.forecasting.targets import MODEL_FEATURES

LOGISTIC_VERSION = "logistic-l2-newton-1"
MAJORITY_VERSION = "majority-train-prevalence-1"
LAST_RETURN_SIGN_VERSION = "last-return-sign-laplace-1"
L2 = 1.0
MAX_ITER = 25
SEED = 0
CONVERGENCE_TOLERANCE = 1e-8
MAX_STEP = 1e6
VARIANCE_FLOOR = 1e-18


def fit_majority(rows: list[dict]) -> dict:
    blocked = _reject_quarantine(rows, "majority_class", MAJORITY_VERSION)
    if blocked is not None:
        return blocked
    if not rows:
        return _failed("majority_class", MAJORITY_VERSION, "NO_TRAINING_ROWS", "Majority class has no training rows.")
    labels = [row["direction"] for row in rows]
    if any(label not in (0, 1) for label in labels):
        return _failed("majority_class", MAJORITY_VERSION, "INVALID_LABEL", "Training labels must be 0 or 1.")
    positives = sum(labels)
    prevalence = positives / len(labels)
    predicted = 1 if prevalence > 0.5 else 0
    return {
        "ok": True,
        "family": "majority_class",
        "model_version": MAJORITY_VERSION,
        "positive_probability": prevalence,
        "hard_class": predicted,
        "tie_predicts_non_positive": True,
        "train_observations": len(labels),
        "seed": SEED,
        "seed_draws_rows": False,
    }


def predict_majority(model: dict, rows: list[dict]) -> list[float]:
    return [model["positive_probability"] for _ in rows]


def fit_last_return_sign(rows: list[dict]) -> dict:
    blocked = _reject_quarantine(rows, "last_return_sign", LAST_RETURN_SIGN_VERSION)
    if blocked is not None:
        return blocked
    if not rows:
        return _failed(
            "last_return_sign",
            LAST_RETURN_SIGN_VERSION,
            "NO_TRAINING_ROWS",
            "The last-return-sign baseline has no training rows.",
        )
    buckets = {0: [0, 0], 1: [0, 0]}
    for row in rows:
        if row["direction"] not in (0, 1):
            return _failed("last_return_sign", LAST_RETURN_SIGN_VERSION, "INVALID_LABEL", "Training labels must be 0 or 1.")
        predicted = _previous_direction(row)
        if predicted is None:
            return _failed(
                "last_return_sign",
                LAST_RETURN_SIGN_VERSION,
                "PREVIOUS_DIRECTION_UNAVAILABLE",
                "ret_1 is not available, so the last completed return has no sign.",
            )
        buckets[predicted][row["direction"]] += 1
    mapping = {}
    for predicted, counts in buckets.items():
        total = counts[0] + counts[1]
        mapping[str(predicted)] = {
            "positive_probability": (counts[1] + 1) / (total + 2),
            "train_count": total,
            "empty_bin": total == 0,
        }
    return {
        "ok": True,
        "family": "last_return_sign",
        "model_version": LAST_RETURN_SIGN_VERSION,
        "rule": "Predict 1 when ret_1 > 0, else 0. Zero ret_1 predicts 0. The Laplace map uses training labels only.",
        "mapping": mapping,
        "seed": SEED,
        "seed_draws_rows": False,
    }


def predict_last_return_sign(model: dict, rows: list[dict]) -> list[float] | None:
    probabilities = []
    for row in rows:
        predicted = _previous_direction(row)
        if predicted is None:
            return None
        probabilities.append(model["mapping"][str(predicted)]["positive_probability"])
    return probabilities


def _previous_direction(row: dict) -> int | None:
    value = row["features"].get("ret_1")
    if value is None or not math.isfinite(value):
        return None
    return 1 if value > 0 else 0


def fit_logistic(rows: list[dict], *, l2: float = L2, max_iter: int = MAX_ITER) -> dict:
    blocked = _reject_quarantine(rows, "logistic_regression", LOGISTIC_VERSION)
    if blocked is not None:
        return blocked
    if not rows:
        return _failed("logistic_regression", LOGISTIC_VERSION, "NO_TRAINING_ROWS", "Logistic regression has no training rows.")
    labels = [row["direction"] for row in rows]
    if any(label not in (0, 1) for label in labels):
        return _failed("logistic_regression", LOGISTIC_VERSION, "INVALID_LABEL", "Training labels must be 0 or 1.")
    if len(set(labels)) < 2:
        return _failed(
            "logistic_regression",
            LOGISTIC_VERSION,
            "SINGLE_CLASS",
            "Training labels contain one class. No probabilities were invented.",
        )
    if not math.isfinite(l2) or l2 < 0 or max_iter < 1:
        return _failed("logistic_regression", LOGISTIC_VERSION, "INVALID_FIT_CONFIG", "The penalty or iteration limit is invalid.")
    matrix = []
    for row in rows:
        values = []
        for name in MODEL_FEATURES:
            value = row["features"].get(name)
            if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
                return _failed(
                    "logistic_regression",
                    LOGISTIC_VERSION,
                    "INVALID_FEATURE",
                    f"{name} is not a finite training value.",
                )
            values.append(float(value))
        matrix.append(values)
    scaled_pack = _scaler(matrix)
    if scaled_pack is None:
        return _failed(
            "logistic_regression",
            LOGISTIC_VERSION,
            "INVALID_FEATURE",
            "A training feature has a non-finite scale.",
        )
    means, scales, zero_variance = scaled_pack
    scaled = [_scale_row(row, means, scales) for row in matrix]
    weights = [0.0 for _ in MODEL_FEATURES]
    intercept = 0.0
    converged = False
    iterations = 0
    for _ in range(max_iter):
        iterations += 1
        step = _newton_step(scaled, labels, weights, intercept, l2)
        if isinstance(step, str):
            return _failed("logistic_regression", LOGISTIC_VERSION, step, "The Newton step was not usable. No probabilities were invented.")
        new_weights, new_intercept = step
        movement = max([abs(new - old) for new, old in zip(new_weights, weights)] + [abs(new_intercept - intercept)])
        weights, intercept = new_weights, new_intercept
        if movement < CONVERGENCE_TOLERANCE:
            converged = True
            break
    if not converged:
        return _failed(
            "logistic_regression",
            LOGISTIC_VERSION,
            "NON_CONVERGED",
            "Newton steps did not reach the convergence tolerance. The unfinished coefficients were discarded.",
        )
    if not all(math.isfinite(weight) for weight in weights) or not math.isfinite(intercept):
        return _failed("logistic_regression", LOGISTIC_VERSION, "INVALID_FIT", "The coefficients are not finite.")
    return {
        "ok": True,
        "family": "logistic_regression",
        "model_version": LOGISTIC_VERSION,
        "feature_names": list(MODEL_FEATURES),
        "scaler": {"means": means, "scales": scales, "zero_variance": zero_variance},
        "weights": weights,
        "intercept": intercept,
        "l2": l2,
        "max_iter": max_iter,
        "iterations": iterations,
        "convergence_tolerance": CONVERGENCE_TOLERANCE,
        "converged": True,
        "threshold": 0.5,
        "threshold_rule": "Class 1 only when the positive probability is greater than 0.5.",
        "missing_data_policy": "exclude_row_if_any_model_feature_not_valid",
        "seed": SEED,
        "seed_draws_rows": False,
    }


def predict_logistic(model: dict, rows: list[dict]) -> list[float] | None:
    if not model.get("ok"):
        return None
    if list(model.get("feature_names") or []) != list(MODEL_FEATURES):
        return None
    means = model["scaler"]["means"]
    scales = model["scaler"]["scales"]
    probabilities = []
    for row in rows:
        scaled = _scale_row([row["features"][name] for name in MODEL_FEATURES], means, scales)
        score = model["intercept"] + sum(weight * value for weight, value in zip(model["weights"], scaled))
        probabilities.append(_sigmoid(score))
    return probabilities


def transform_means(rows: list[dict]) -> list[float]:
    matrix = [[row["features"][name] for name in MODEL_FEATURES] for row in rows]
    means, _, _ = _scaler(matrix)
    return means


def _scaler(matrix: list[list[float]]) -> tuple[list[float], list[float], list[str]] | None:
    count = len(matrix)
    width = len(matrix[0])
    if any(not math.isfinite(value) for row in matrix for value in row):
        return None
    means = [sum(row[index] for row in matrix) / count for index in range(width)]
    scales: list[float] = []
    zero_variance: list[str] = []
    for index in range(width):
        variance = sum((row[index] - means[index]) ** 2 for row in matrix) / (count - 1)
        if not math.isfinite(variance):
            return None
        if variance <= VARIANCE_FLOOR:
            scales.append(0.0)
            zero_variance.append(MODEL_FEATURES[index])
        else:
            scales.append(math.sqrt(variance))
    return means, scales, zero_variance


def _scale_row(row: list[float], means: list[float], scales: list[float]) -> list[float]:
    scaled = []
    for value, mean, scale in zip(row, means, scales):
        if scale == 0:
            scaled.append(0.0)
        else:
            scaled.append((value - mean) / scale)
    return scaled


def _sigmoid(score: float) -> float:
    if score >= 0:
        return 1 / (1 + math.exp(-score))
    exponential = math.exp(score)
    return exponential / (1 + exponential)


def _reject_quarantine(rows: list[dict], family: str, version: str) -> dict | None:
    from app.market.provenance import quarantine_training_block

    blocked = quarantine_training_block({"rows": rows})
    if blocked is None:
        return None
    return _failed(family, version, blocked[0], blocked[1])


def _failed(family: str, version: str, code: str, message: str) -> dict:
    return {"ok": False, "code": code, "family": family, "model_version": version, "message": message}


def _newton_step(
    scaled: list[list[float]],
    labels: list[int],
    weights: list[float],
    intercept: float,
    l2: float,
) -> tuple[list[float], float] | str:
    width = len(weights)
    gradient = [0.0 for _ in range(width + 1)]
    hessian = [[0.0 for _ in range(width + 1)] for _ in range(width + 1)]
    count = len(labels)
    for row, label in zip(scaled, labels):
        score = intercept + sum(weight * value for weight, value in zip(weights, row))
        probability = _sigmoid(score)
        residual = probability - label
        weight_term = probability * (1 - probability)
        for index, value in enumerate(row):
            gradient[index] += residual * value
        gradient[width] += residual
        for left, left_value in enumerate(row):
            for right, right_value in enumerate(row):
                hessian[left][right] += weight_term * left_value * right_value
            hessian[left][width] += weight_term * left_value
            hessian[width][left] += weight_term * left_value
        hessian[width][width] += weight_term
    for index in range(width + 1):
        gradient[index] /= count
        for right in range(width + 1):
            hessian[index][right] /= count
    for index in range(width):
        gradient[index] += l2 * weights[index]
        hessian[index][index] += l2
    delta = _solve(hessian, gradient)
    if delta is None:
        return "SINGULAR_HESSIAN"
    rejection = _reject_step(delta)
    if rejection is not None:
        return rejection
    return [weight - step for weight, step in zip(weights, delta[:-1])], intercept - delta[-1]


def _reject_step(delta: list[float]) -> str | None:
    if any(not math.isfinite(value) for value in delta):
        return "INVALID_FIT"
    if max(abs(value) for value in delta) > MAX_STEP:
        return "ILL_CONDITIONED"
    return None


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    rows = [matrix[index][:] + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        for index in range(column, size + 1):
            rows[column][index] /= divisor
        for row in range(size):
            if row == column:
                continue
            factor = rows[row][column]
            for index in range(column, size + 1):
                rows[row][index] -= factor * rows[column][index]
    return [rows[index][size] for index in range(size)]
