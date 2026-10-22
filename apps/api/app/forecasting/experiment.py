"""Run the M3 holdout and seal an experiment artifact.

The test period is scored once. It is not used to choose the model.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.features.definitions import FEATURE_SET_VERSION
from app.features.pipeline import content_hash
from app.forecasting.metrics import binary_metrics
from app.forecasting.models import (
    SEED,
    fit_last_return_sign,
    fit_logistic,
    fit_majority,
    predict_last_return_sign,
    predict_logistic,
    predict_majority,
    transform_means,
)
from app.forecasting.splits import EVALUATION_VERSION, SplitConfig, chronological_split
from app.forecasting.targets import MODEL_FEATURES, TARGET_ID, TARGET_VERSION, label_dataset
from app.market.provenance import data_category, evaluation_block

TRAINING_CODE_VERSION = "m3"
SELECTION_TOLERANCE = 1e-12
SELECTION_INPUTS = ["validation_log_loss", "validation_brier", "model_name"]


def run_experiment(
    dataset: dict,
    *,
    config: SplitConfig | None = None,
    target_version: str = TARGET_VERSION,
    require_verified_history: bool = False,
) -> dict:
    if target_version != TARGET_VERSION:
        return _failure("TARGET_VERSION_MISMATCH", "The only implemented target is binary-1.")
    blocked = evaluation_block(dataset, require_verified_history=require_verified_history)
    if blocked is not None:
        return _failure(blocked[0], blocked[1])
    if not _dataset_checksum(dataset):
        return _failure("CHECKSUM_MISMATCH", "The feature dataset checksum does not match its contents.")
    labeled = label_dataset(dataset)
    if not labeled["ok"]:
        return _failure(labeled["code"], labeled.get("message", "Labels were not created."), eligibility=labeled)
    config = config or SplitConfig()
    split = chronological_split(labeled["rows"], config)
    eligibility = {key: value for key, value in labeled.items() if key != "rows"}
    if not split["ok"]:
        return _failure(split["code"], split.get("message", "The split was not created."), eligibility=eligibility, split=split)
    alignment = _alignment_error(split)
    if alignment is not None:
        return _failure(alignment[0], alignment[1], eligibility=eligibility)
    models = {
        "majority_class": fit_majority(split["train"]),
        "last_return_sign": fit_last_return_sign(split["train"]),
        "logistic_regression": fit_logistic(split["train"]),
    }
    validation_metrics = _score_all(models, split["validation"])
    test_metrics = _score_all(models, split["test"])
    if _counts_diverge(validation_metrics) or _counts_diverge(test_metrics):
        return _failure(
            "METRIC_ROW_MISMATCH",
            "Compared models did not score the same observations.",
            eligibility=eligibility,
        )
    selected = choose_model(validation_metrics)
    if selected is None:
        return _failure(
            "NO_SELECTABLE_MODEL",
            "No model produced a defined validation log loss.",
            eligibility=eligibility,
        )
    body = {
        "evaluation_version": EVALUATION_VERSION,
        "training_code_version": TRAINING_CODE_VERSION,
        "target_id": TARGET_ID,
        "target_version": TARGET_VERSION,
        "feature_set_version": dataset.get("feature_set_version"),
        "feature_names": list(MODEL_FEATURES),
        "training_dataset_id": dataset.get("dataset_id"),
        "instrument": dataset.get("instrument_id"),
        "interval": dataset.get("interval"),
        "origin": dataset.get("origin"),
        "lineage": dataset.get("lineage"),
        "data_category": data_category(dataset),
        "source_id": dataset.get("source_id"),
        "synthetic": dataset.get("synthetic"),
        "created_at": dataset.get("created_at"),
        "split": split["manifest"],
        "split_config": split["config"],
        "eligibility": eligibility,
        "models": models,
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "selected_model": selected,
        "selection_metric": "log_loss",
        "selection_tolerance": SELECTION_TOLERANCE,
        "selection_tie_break": ["log_loss", "brier", "model_name"],
        "selection_inputs": SELECTION_INPUTS,
        "test_used_for_selection": False,
        "test_report_count": 1,
        "untouched_for_selection": True,
        "identity_excludes_write_time": True,
        "untouched_note": (
            "Test metrics were written once and did not choose the model, the threshold, "
            "or the preprocessing. Changing the model because of this test spends the untouched period."
        ),
        "seed": SEED,
        "seed_draws_rows": False,
        "forecast_ready": False,
        "approved_for_paper": False,
        "approved_for_live": False,
        "production_approved": False,
        "readiness": readiness(
            training_completed=True,
            evaluation_completed=True,
            out_of_sample_evaluation_completed=True,
            calibration_evaluated=any(
                report.get("calibration", {}).get("status") == "COMPUTED" for report in test_metrics.values()
            ),
        ),
    }
    artifact = _seal(body)
    return {"ok": True, "code": None, "forecast_ready": False, "artifact": artifact}


def choose_model(metrics: dict[str, dict]) -> str | None:
    """Pick the lowest validation log loss. Ties within 1e-12 use Brier, then name.

    Callers must pass validation metrics. Test metrics are not an input.
    """
    ranked: list[tuple[float, float, str]] = []
    for name, report in metrics.items():
        log_loss = (report.get("log_loss") or {}).get("value")
        brier = (report.get("brier") or {}).get("value")
        if log_loss is None or brier is None:
            continue
        ranked.append((float(log_loss), float(brier), name))
    if not ranked:
        return None
    winner = ranked[0]
    for candidate in ranked[1:]:
        if _lower_score(candidate[0], winner[0]):
            winner = candidate
        elif _tied(candidate[0], winner[0]) and _lower_score(candidate[1], winner[1]):
            winner = candidate
        elif _tied(candidate[0], winner[0]) and _tied(candidate[1], winner[1]) and candidate[2] < winner[2]:
            winner = candidate
    return winner[2]


def _lower_score(left: float, right: float) -> bool:
    return left < right - SELECTION_TOLERANCE


def _tied(left: float, right: float) -> bool:
    return abs(left - right) <= SELECTION_TOLERANCE


def readiness(
    *,
    training_completed: bool = False,
    evaluation_completed: bool = False,
    out_of_sample_evaluation_completed: bool = False,
    calibration_evaluated: bool = False,
) -> dict:
    report = {
        "pipeline_tests_passed": None,
        "training_completed": training_completed,
        "evaluation_completed": evaluation_completed,
        "real_market_data_verified": False,
        "out_of_sample_evaluation_completed": out_of_sample_evaluation_completed,
        "calibration_evaluated": calibration_evaluated,
        "calibration_accepted": False,
        "production_approved": False,
    }
    unmet = [
        "PIPELINE_TESTS_NOT_ATTESTED",
        "REAL_MARKET_DATA_NOT_VERIFIED",
        "CALIBRATION_NOT_ACCEPTED",
        "PRODUCTION_NOT_APPROVED",
        "NO_PREDICTIVE_EDGE_CLAIM",
        "NO_TRADING_APPROVAL",
    ]
    if not training_completed:
        unmet.append("TRAINING_NOT_COMPLETED")
    if not evaluation_completed:
        unmet.append("EVALUATION_NOT_COMPLETED")
    if not out_of_sample_evaluation_completed:
        unmet.append("OUT_OF_SAMPLE_EVALUATION_NOT_COMPLETED")
    report["unmet_requirements"] = unmet
    report["forecast_ready"] = False
    return report


def training_scaler_means(rows: list[dict]) -> list[float]:
    return transform_means(rows)


def score_saved_logistic(artifact: dict, rows: list[dict]) -> dict:
    """Score rows with a sealed experiment. The caller passes the artifact, not a path."""
    if not _experiment_checksum(artifact):
        return _failure("CHECKSUM_MISMATCH", "The experiment checksum does not match its contents.")
    if artifact.get("target_version") != TARGET_VERSION or artifact.get("feature_set_version") != FEATURE_SET_VERSION:
        return _failure("VERSION_MISMATCH", "The artifact target or feature set is not the implemented pair.")
    if artifact.get("forecast_ready") is not False or artifact.get("production_approved") is not False:
        return _failure("APPROVAL_REFUSED", "This artifact cannot be loaded as an approved model.")
    model = (artifact.get("models") or {}).get("logistic_regression")
    if not model or not model.get("ok"):
        return _failure("MODEL_UNAVAILABLE", "The saved logistic model did not train.")
    if list(model.get("feature_names") or []) != list(MODEL_FEATURES):
        return _failure("FEATURE_MISMATCH", f"The saved features do not match {FEATURE_SET_VERSION} model inputs.")
    probabilities = predict_logistic(model, rows)
    if probabilities is None:
        return _failure("MODEL_UNAVAILABLE", "The saved logistic model did not score.")
    return {
        "ok": True,
        "forecast_ready": False,
        "synthetic": artifact.get("synthetic"),
        "origin": artifact.get("origin"),
        "probabilities": probabilities,
        "production_approved": False,
    }


def _score_all(models: dict, rows: list[dict]) -> dict:
    reports = {}
    if models["majority_class"].get("ok"):
        reports["majority_class"] = binary_metrics(
            [row["direction"] for row in rows],
            predict_majority(models["majority_class"], rows),
        )
    if models["last_return_sign"].get("ok"):
        probabilities = predict_last_return_sign(models["last_return_sign"], rows)
        if probabilities is not None:
            reports["last_return_sign"] = binary_metrics([row["direction"] for row in rows], probabilities)
    if models["logistic_regression"].get("ok"):
        probabilities = predict_logistic(models["logistic_regression"], rows)
        if probabilities is not None:
            reports["logistic_regression"] = binary_metrics([row["direction"] for row in rows], probabilities)
    return reports


def _counts_diverge(metrics: dict[str, dict]) -> bool:
    counts = {report.get("observations") for report in metrics.values()}
    return len(counts) > 1


def _alignment_error(split: dict) -> tuple[str, str] | None:
    validation_times = [_parse(row["as_of"]) for row in split["validation"]]
    test_times = [_parse(row["as_of"]) for row in split["test"]]
    for row in split["train"]:
        label_at = _parse(row["label_available_at"])
        if label_at >= min(validation_times) or any(label_at >= moment for moment in test_times):
            return ("FUTURE_LABEL_IN_TRAIN", "A training label uses a later evaluation candle.")
        if _parse(row["as_of"]) >= label_at:
            return ("LABEL_ALIGNMENT", "A label is not strictly after its feature timestamp.")
    for row in split["validation"]:
        label_at = _parse(row["label_available_at"])
        if any(label_at >= moment for moment in test_times):
            return ("FUTURE_LABEL_IN_VALIDATION", "A validation label uses a test candle.")
        if _parse(row["as_of"]) >= label_at:
            return ("LABEL_ALIGNMENT", "A label is not strictly after its feature timestamp.")
    for row in split["test"]:
        if _parse(row["as_of"]) >= _parse(row["label_available_at"]):
            return ("LABEL_ALIGNMENT", "A label is not strictly after its feature timestamp.")
    return None


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _dataset_checksum(artifact: dict) -> bool:
    body = {key: value for key, value in artifact.items() if key not in {"dataset_id", "checksum"}}
    digest = content_hash(body)
    return artifact.get("dataset_id") == digest and artifact.get("checksum") == digest


def _experiment_checksum(artifact: dict) -> bool:
    body = {key: value for key, value in artifact.items() if key not in {"experiment_id", "checksum"}}
    digest = content_hash(body)
    return artifact.get("experiment_id") == digest and artifact.get("checksum") == digest


def _seal(body: dict) -> dict:
    frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":")))
    digest = content_hash(frozen)
    frozen["experiment_id"] = digest
    frozen["checksum"] = digest
    return frozen


def _failure(code: str, message: str, *, eligibility: dict | None = None, split: dict | None = None) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "forecast_ready": False,
        "artifact": None,
        "eligibility": eligibility,
        "split": split,
        "readiness": readiness(),
    }
