"""Expanding-window walk-forward evaluation on the M3 binary target.

Training grows by step_size. Validation and test sizes stay fixed.
A fold that is short after the embargo is recorded as a failure.
Its window is not resized, and a failed model is not replaced.
"""

from __future__ import annotations

import json
import statistics

from pydantic import BaseModel, ConfigDict

from app.features.pipeline import content_hash
from app.forecasting.experiment import (
    SELECTION_INPUTS,
    SELECTION_TOLERANCE,
    _alignment_error,
    _counts_diverge,
    _dataset_checksum,
    _score_all,
    choose_model,
    readiness,
)
from app.forecasting.models import (
    SEED,
    fit_last_return_sign,
    fit_logistic,
    fit_majority,
    predict_last_return_sign,
    predict_logistic,
    predict_majority,
)
from app.forecasting.splits import EMBARGO_RULE, window_split
from app.forecasting.store import WalkForwardStore
from app.forecasting.targets import MODEL_FEATURES, TARGET_ID, TARGET_VERSION, label_dataset
from app.market.provenance import data_category, evaluation_block
from app.settings import REPO_ROOT

EVALUATION_VERSION = "m4-expanding-1"
TRAINING_CODE_VERSION = "m4"
METRIC_NAMES = ("accuracy", "balanced_accuracy", "precision", "recall", "f1", "log_loss", "brier")
MODEL_NAMES = ("majority_class", "last_return_sign", "logistic_regression")
HARD_FOLD_FAILURES = {
    "LEAKAGE_DETECTED",
    "INVALID_BOUNDARY",
    "AMBIGUOUS_TIME",
    "DUPLICATE_OBSERVATION",
    "UNSUPPORTED_EMBARGO",
    "INVALID_TIMESTAMP",
}
PREDICTORS = {
    "majority_class": predict_majority,
    "last_return_sign": predict_last_return_sign,
    "logistic_regression": predict_logistic,
}


class WalkForwardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_train_size: int = 9
    validation_size: int = 5
    test_size: int = 4
    step_size: int = 4
    min_train: int = 8
    min_validation: int = 4
    min_test: int = 4
    embargo_bars: int = 1
    seed: int = 0


def walkforward_store() -> WalkForwardStore:
    return WalkForwardStore(REPO_ROOT / "var" / "walkforward")


def run_walk_forward(
    dataset: dict,
    *,
    config: WalkForwardConfig | None = None,
    target_version: str = TARGET_VERSION,
    require_verified_history: bool = False,
) -> dict:
    if target_version != TARGET_VERSION:
        return _failure("TARGET_VERSION_MISMATCH", "The only implemented target is binary-1.")
    from app.market.provenance import quarantine_training_block

    quarantined = quarantine_training_block(dataset)
    if quarantined is not None:
        return _failure(quarantined[0], quarantined[1])
    blocked = evaluation_block(dataset, require_verified_history=require_verified_history)
    if blocked is not None:
        return _failure(blocked[0], blocked[1])
    if not _dataset_checksum(dataset):
        return _failure("CHECKSUM_MISMATCH", "The feature dataset checksum does not match its contents.")
    labeled = label_dataset(dataset)
    if not labeled["ok"]:
        return _failure(labeled["code"], labeled.get("message", "Labels were not created."), eligibility=labeled)
    config = config or WalkForwardConfig()
    config_error = _validate_config(config)
    if config_error is not None:
        return _failure(config_error[0], config_error[1])
    eligibility = {key: value for key, value in labeled.items() if key != "rows"}
    windows = _windows(len(labeled["rows"]), config)
    if not windows:
        return _failure(
            "INSUFFICIENT_DATA",
            "The series cannot hold one configured train, validation, and test window.",
            eligibility=eligibility,
        )
    folds = []
    for index, bounds in enumerate(windows):
        try:
            fold = _evaluate_fold(index, labeled["rows"], bounds, config, eligibility)
        except ValueError as exc:
            return _failure("INVALID_TIMESTAMP", str(exc), eligibility=eligibility)
        if fold.get("code") in HARD_FOLD_FAILURES:
            return _failure(fold["code"], fold.get("message") or fold["code"], eligibility=eligibility)
        folds.append(fold)
    if _tests_overlap(folds):
        return _failure("OVERLAPPING_TEST", "Test windows overlap. The step is not smaller than the test size.", eligibility=eligibility)
    body = _artifact_body(dataset, labeled, config, folds)
    return {"ok": True, "code": None, "forecast_ready": False, "artifact": _seal(body)}


def _validate_config(config: WalkForwardConfig) -> tuple[str, str] | None:
    sizes = (
        config.initial_train_size,
        config.validation_size,
        config.test_size,
        config.step_size,
        config.min_train,
        config.min_validation,
        config.min_test,
    )
    if any(size < 1 for size in sizes):
        return ("INVALID_CONFIG", "Window sizes and minimums must be at least 1.")
    if config.step_size < config.test_size:
        return ("OVERLAPPING_TEST", "step_size must be at least test_size so test windows do not overlap.")
    if config.embargo_bars != 1:
        return ("UNSUPPORTED_EMBARGO", "binary-1 keeps the one-bar embargo.")
    return None


def _windows(count: int, config: WalkForwardConfig) -> list[tuple[int, int, int]]:
    windows = []
    index = 0
    while True:
        train_end = config.initial_train_size + index * config.step_size
        validation_end = train_end + config.validation_size
        test_end = validation_end + config.test_size
        if test_end > count:
            break
        windows.append((train_end, validation_end, test_end))
        index += 1
    return windows


def _evaluate_fold(
    index: int,
    rows: list[dict],
    bounds: tuple[int, int, int],
    config: WalkForwardConfig,
    eligibility: dict,
) -> dict:
    train_end, validation_end, test_end = bounds
    window = window_split(
        rows,
        train_end=train_end,
        validation_end=validation_end,
        test_end=test_end,
        embargo_bars=config.embargo_bars,
    )
    base = _fold_header(index, bounds, config, eligibility)
    if not window["ok"]:
        return {**base, "ok": False, "code": window["code"], "message": window["message"]}
    kept = {
        "train": len(window["train"]),
        "validation": len(window["validation"]),
        "test": len(window["test"]),
    }
    base.update(
        {
            "raw_train_count": window["raw_train_count"],
            "raw_validation_count": window["raw_validation_count"],
            "raw_test_count": window["raw_test_count"],
            "eligible_train_count": kept["train"],
            "eligible_validation_count": kept["validation"],
            "eligible_test_count": kept["test"],
            "embargo_train_keys": window["embargo_train_keys"],
            "embargo_validation_keys": window["embargo_validation_keys"],
            "embargo_rule": window["embargo_rule"],
            "train_start": window["train_start"],
            "train_end": window["train_end"],
            "validation_start": window["validation_start"],
            "validation_end": window["validation_end"],
            "test_start": window["test_start"],
            "test_end": window["test_end"],
            "eligible_train_start": window["train"][0]["as_of"] if window["train"] else None,
            "eligible_train_end": window["train"][-1]["as_of"] if window["train"] else None,
            "eligible_validation_start": window["validation"][0]["as_of"] if window["validation"] else None,
            "eligible_validation_end": window["validation"][-1]["as_of"] if window["validation"] else None,
            "positive_prevalence": _prevalence(window["test"]),
            "excluded_reasons": {
                "EMBARGO_TRAIN": len(window["embargo_train_keys"]),
                "EMBARGO_VALIDATION": len(window["embargo_validation_keys"]),
            },
        }
    )
    if (
        kept["train"] < config.min_train
        or kept["validation"] < config.min_validation
        or kept["test"] < config.min_test
    ):
        return {
            **base,
            "ok": False,
            "code": "INSUFFICIENT_AFTER_EMBARGO",
            "message": "This fold is below a configured minimum after the embargo. The window was not resized.",
        }
    alignment = _alignment_error(window)
    if alignment is not None:
        return {**base, "ok": False, "code": "LEAKAGE_DETECTED", "message": alignment[1]}
    models = {
        "majority_class": fit_majority(window["train"]),
        "last_return_sign": fit_last_return_sign(window["train"]),
        "logistic_regression": fit_logistic(window["train"]),
    }
    validation_metrics = _score_all(models, window["validation"])
    test_metrics = _score_all(models, window["test"])
    if _counts_diverge(validation_metrics) or _counts_diverge(test_metrics):
        return {
            **base,
            "ok": False,
            "code": "METRIC_ROW_MISMATCH",
            "message": "Models did not score the same validation or test rows.",
            "model_results": _model_results(models, validation_metrics, test_metrics),
        }
    selected = choose_model(validation_metrics)
    results = _model_results(models, validation_metrics, test_metrics)
    if selected is None:
        return {
            **base,
            "ok": False,
            "code": "NO_SELECTABLE_MODEL",
            "message": "No model produced a defined validation log loss. No substitute was chosen.",
            "model_results": results,
        }
    probabilities = _probabilities(selected, models[selected], window["test"])
    if probabilities is None or len(probabilities) != len(window["test"]):
        return {
            **base,
            "ok": False,
            "code": "SCORE_FAILED",
            "message": "The validation-selected model did not score the test rows. No other model was substituted.",
            "model_results": results,
            "selected_model": selected,
        }
    return {
        **base,
        "ok": True,
        "code": None,
        "model_results": results,
        "selected_model": selected,
        "selected_model_result": {"validation": validation_metrics[selected], "test": test_metrics[selected]},
        "selected_test_predictions": [
            {"key": row["key"], "direction": row["direction"], "probability": probability}
            for row, probability in zip(window["test"], probabilities)
        ],
        "test_used_for_selection": False,
    }


def _fold_header(index: int, bounds: tuple[int, int, int], config: WalkForwardConfig, eligibility: dict) -> dict:
    train_end, validation_end, test_end = bounds
    return {
        "fold_id": f"fold-{index}",
        "dataset_id": eligibility.get("source_dataset_id"),
        "feature_set_version": "ohlc-1",
        "target_version": TARGET_VERSION,
        "evaluation_version": EVALUATION_VERSION,
        "embargo_rule": EMBARGO_RULE,
        "train_end_index": train_end,
        "validation_end_index": validation_end,
        "test_end_index": test_end,
        "window_policy": "expanding_train_fixed_validation_and_test",
        "config": config.model_dump(mode="json"),
    }


def _model_results(models: dict, validation_metrics: dict, test_metrics: dict) -> dict:
    results = {}
    for name in MODEL_NAMES:
        fit = models[name]
        scored = fit.get("ok") and name in validation_metrics and name in test_metrics
        results[name] = {
            "fit": fit,
            "validation": validation_metrics.get(name),
            "test": test_metrics.get(name),
            "failure": None if scored else (fit.get("code") or "SCORE_FAILED"),
        }
    return results


def _probabilities(name: str, model: dict, rows: list[dict]) -> list[float] | None:
    if not model.get("ok"):
        return None
    try:
        return PREDICTORS[name](model, rows)
    except (KeyError, TypeError, ValueError):
        return None


def _prevalence(rows: list[dict]) -> float | None:
    if not rows:
        return None
    return sum(row["direction"] for row in rows) / len(rows)


def _tests_overlap(folds: list[dict]) -> bool:
    seen: set[str] = set()
    for fold in folds:
        if not fold.get("ok"):
            continue
        for prediction in fold["selected_test_predictions"]:
            if prediction["key"] in seen:
                return True
            seen.add(prediction["key"])
    return False


def _artifact_body(dataset: dict, labeled: dict, config: WalkForwardConfig, folds: list[dict]) -> dict:
    successful = [fold for fold in folds if fold.get("ok")]
    selections: dict[str, int] = {name: 0 for name in MODEL_NAMES}
    for fold in successful:
        selections[fold["selected_model"]] += 1
    return {
        "evaluation_version": EVALUATION_VERSION,
        "training_code_version": TRAINING_CODE_VERSION,
        "window_policy": "expanding_train_fixed_validation_and_test",
        "window_note": (
            "Each later fold keeps the same first training row and adds step_size rows. "
            "Validation and test lengths stay at the configured sizes. "
            "A later fold may train on rows that were test rows in an earlier fold, "
            "because those rows now precede its own test window."
        ),
        "target_id": TARGET_ID,
        "target_version": TARGET_VERSION,
        "feature_set_version": dataset.get("feature_set_version"),
        "feature_names": list(MODEL_FEATURES),
        "training_dataset_id": dataset.get("dataset_id"),
        "dataset_checksum": dataset.get("checksum"),
        "instrument": dataset.get("instrument_id"),
        "interval": dataset.get("interval"),
        "origin": dataset.get("origin"),
        "lineage": dataset.get("lineage"),
        "data_category": data_category(dataset),
        "source_id": dataset.get("source_id"),
        "synthetic": bool(dataset.get("synthetic")),
        "documented_sample": dataset.get("origin") == "DOCUMENTED_SAMPLE",
        "performance_claim_allowed": False,
        "created_at": dataset.get("created_at"),
        "identity_excludes_write_time": True,
        "config": config.model_dump(mode="json"),
        "embargo_rule": EMBARGO_RULE,
        "eligibility": {key: value for key, value in labeled.items() if key != "rows"},
        "result_categories": {
            "model_results": "Every fitted model is scored on the same validation rows and the same test rows. Those test scores do not select the model.",
            "selected_model_result": "Test metrics of the one model chosen from validation log loss, then Brier score, then name.",
        },
        "selection_metric": "log_loss",
        "selection_tolerance": SELECTION_TOLERANCE,
        "selection_inputs": SELECTION_INPUTS,
        "folds": folds,
        "aggregate": _aggregate(folds),
        "selection_counts": selections,
        "successful_folds": len(successful),
        "failed_folds": len(folds) - len(successful),
        "seed": SEED,
        "seed_draws_rows": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "production_approved": False,
        "readiness": readiness(
            training_completed=bool(successful),
            evaluation_completed=bool(successful),
            out_of_sample_evaluation_completed=bool(successful),
            calibration_evaluated=any(
                (fold.get("selected_model_result") or {}).get("test", {}).get("calibration", {}).get("status") == "COMPUTED"
                for fold in successful
            ),
        ),
    }


def _aggregate(folds: list[dict]) -> dict:
    successful = [fold for fold in folds if fold.get("ok")]
    pooled_labels: list[int] = []
    pooled_probabilities: list[float] = []
    for fold in successful:
        for prediction in fold["selected_test_predictions"]:
            pooled_labels.append(prediction["direction"])
            pooled_probabilities.append(prediction["probability"])
    from app.forecasting.metrics import binary_metrics

    pooled = binary_metrics(pooled_labels, pooled_probabilities) if pooled_labels else {"status": "NO_OBSERVATIONS"}
    return {
        "fold_count": len(folds),
        "successful_folds": len(successful),
        "failed_folds": len(folds) - len(successful),
        "failed_fold_ids": [fold["fold_id"] for fold in folds if not fold.get("ok")],
        "total_scored_test_observations": len(pooled_labels),
        "positive_prevalence_by_fold": [
            {"fold_id": fold["fold_id"], "positive_prevalence": fold.get("positive_prevalence")} for fold in folds
        ],
        "macro": {name: _macro(successful, name) for name in MODEL_NAMES},
        "macro_selected_model": _macro_selected(successful),
        "pooled_selected_model": pooled,
        "aggregation_notes": {
            "macro": "Each successful fold has equal weight. Undefined metric values are omitted, not treated as zero.",
            "pooled": "Selected-model test predictions are concatenated. This is not an average of rates. Test windows do not overlap.",
            "confusion_matrix": "Per-fold matrices stay on the fold. They are not averaged. The pooled matrix is inside pooled_selected_model.",
            "calibration": "A computed log loss or Brier score does not mean the probabilities are calibrated.",
        },
    }


def _macro(folds: list[dict], model_name: str) -> dict:
    per_metric = {}
    for metric in METRIC_NAMES:
        values = []
        omitted = 0
        for fold in folds:
            report = ((fold.get("model_results") or {}).get(model_name) or {}).get("test") or {}
            item = report.get(metric) or {}
            if item.get("value") is None:
                omitted += 1
                continue
            values.append(item["value"])
        per_metric[metric] = _summarize(values, omitted)
    return per_metric


def _macro_selected(folds: list[dict]) -> dict:
    per_metric = {}
    for metric in METRIC_NAMES:
        values = []
        omitted = 0
        for fold in folds:
            item = ((fold.get("selected_model_result") or {}).get("test") or {}).get(metric) or {}
            if item.get("value") is None:
                omitted += 1
                continue
            values.append(item["value"])
        per_metric[metric] = _summarize(values, omitted)
    return per_metric


def _summarize(values: list[float], omitted: int) -> dict:
    if not values:
        return {"value": None, "mean": None, "median": None, "stdev": None, "status": "UNDEFINED", "contributing_folds": 0, "omitted_undefined": omitted}
    summary = {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) >= 2 else None,
        "status": "DEFINED" if len(values) >= 2 else "UNDEFINED_SINGLE_FOLD_STDEV",
        "contributing_folds": len(values),
        "omitted_undefined": omitted,
        "method": "macro_equal_fold_weight",
    }
    return summary


def _seal(body: dict) -> dict:
    frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":")))
    digest = content_hash(frozen)
    frozen["walkforward_id"] = digest
    frozen["checksum"] = digest
    return frozen


def _failure(code: str, message: str, *, eligibility: dict | None = None) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "artifact": None,
        "eligibility": eligibility,
        "readiness": readiness(),
    }


def run_from_provider(
    instrument: str,
    *,
    provider_name: str,
    retrieved_at,
    config: WalkForwardConfig | None = None,
) -> dict:
    """Build the named provider's dataset, then evaluate it. The caller cannot pass a path."""
    from datetime import datetime

    from app.features.pipeline import DatasetBuildResult
    from app.features.service import build_from_provider, feature_store

    if not isinstance(retrieved_at, datetime):
        return _failure("INVALID_TIMESTAMP", "retrieved_at must be a datetime.")
    loaded = build_from_provider(
        instrument,
        provider_name=provider_name,
        retrieved_at=retrieved_at,
        store=feature_store(),
    )
    if not isinstance(loaded, DatasetBuildResult):
        return _failure(loaded.code, loaded.message)
    if not loaded.ok or loaded.artifact is None:
        return _failure(loaded.code or "DATASET_REJECTED", loaded.message or "The feature dataset was not built.")
    evaluated = run_walk_forward(loaded.artifact, config=config)
    if evaluated.get("ok") and evaluated.get("artifact") is not None:
        walkforward_store().write(evaluated["artifact"])
    return evaluated
