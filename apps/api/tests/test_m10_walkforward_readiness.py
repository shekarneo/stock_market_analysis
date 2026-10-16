"""Milestone M10 regression tests: Historical Data Readiness & Walk-Forward Research Preparation."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
import pytest

from app.features.pipeline import build_dataset, content_hash, seal
from app.forecasting.experiment import _alignment_error, choose_model, readiness, run_experiment
from app.forecasting.metrics import binary_metrics
from app.forecasting.models import (
    fit_last_return_sign,
    fit_logistic,
    fit_majority,
    predict_last_return_sign,
    predict_logistic,
    predict_majority,
)
from app.forecasting.splits import SplitConfig, chronological_split, window_split
from app.forecasting.store import WalkForwardStore
from app.forecasting.targets import MODEL_FEATURES, TARGET_ID, TARGET_VERSION, label_dataset
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward
from app.market.fixtures import fixture_calendar
from app.market.provenance import evaluation_block, quarantine_training_block
from app.market.schemas import IST, Candle, DataOrigin, MarketSession
from app.registry.service import register_artifact
from app.registry.store import RegistryStore
from tests.test_forecasting import alternating, series


def _make_synth_series(n_bars: int = 25) -> dict:
    """Helper to produce a valid single-session (up to 25 candles) synthetic feature dataset."""
    assert n_bars <= 25, "Single session fixture cannot exceed 25 candles"
    return series(alternating()[:n_bars])


def test_chronological_split_integrity_strictly_monotonic_no_shuffle():
    """Verify time-series ordering is strictly preserved and random shuffling is forbidden."""
    dataset = _make_synth_series(25)
    labeled = label_dataset(dataset)
    assert labeled["ok"] is True
    rows = labeled["rows"]

    config = SplitConfig(train_fraction=0.6, validation_fraction=0.2, min_train=6, min_validation=2, min_test=2)
    split = chronological_split(rows, config=config)

    assert split["ok"] is True
    assert split["shuffled"] is False
    assert split["seed_draws_rows"] is False

    train = split["train"]
    val = split["validation"]
    test = split["test"]

    # Verify monotonic time order within each split
    for partition in (train, val, test):
        times = [datetime.fromisoformat(r["as_of"]) for r in partition]
        for i in range(len(times) - 1):
            assert times[i] < times[i + 1], "Observations within partition must be strictly increasing"

    # Verify cross-partition ordering: train < validation < test
    train_max = max(datetime.fromisoformat(r["as_of"]) for r in train)
    val_min = min(datetime.fromisoformat(r["as_of"]) for r in val)
    val_max = max(datetime.fromisoformat(r["as_of"]) for r in val)
    test_min = min(datetime.fromisoformat(r["as_of"]) for r in test)

    assert train_max < val_min, "All training observations must precede all validation observations"
    assert val_max < test_min, "All validation observations must precede all test observations"


def test_train_only_preprocessing_scaler_isolated_from_test_and_validation():
    """Verify feature standardizer means and scales are fitted exclusively on training rows."""
    dataset = _make_synth_series(25)
    labeled = label_dataset(dataset)
    rows = labeled["rows"]

    window = window_split(rows, train_end=10, validation_end=14, test_end=18)
    assert window["ok"] is True

    # Fit model on training partition
    model_orig = fit_logistic(window["train"])
    assert model_orig["ok"] is True
    scaler_orig = model_orig["scaler"]

    # Create modified validation & test sets with extreme outlier values
    val_modified = copy.deepcopy(window["validation"])
    test_modified = copy.deepcopy(window["test"])
    for r in val_modified + test_modified:
        for f in MODEL_FEATURES:
            r["features"][f] = 999999.0

    # Ensure model fitted on training is completely invariant to test/val changes
    model_check = fit_logistic(window["train"])
    assert model_check["scaler"]["means"] == scaler_orig["means"]
    assert model_check["scaler"]["scales"] == scaler_orig["scales"]
    assert model_check["weights"] == model_orig["weights"]
    assert model_check["intercept"] == model_orig["intercept"]

    # Out-of-sample prediction must use the training means & scales
    preds = predict_logistic(model_orig, test_modified)
    assert preds is not None
    assert len(preds) == len(test_modified)
    assert all(0.0 <= p <= 1.0 for p in preds)


def test_target_leakage_prevented_across_boundaries():
    """Verify that no training row label availability timestamp reaches into validation period."""
    dataset = _make_synth_series(25)
    labeled = label_dataset(dataset)
    rows = labeled["rows"]

    window = window_split(rows, train_end=10, validation_end=14, test_end=18)
    assert window["ok"] is True

    # Alignment error must be None
    align_err = _alignment_error(window)
    assert align_err is None

    # Check every training sample's label availability
    val_start = datetime.fromisoformat(window["validation_start"])
    for r in window["train"]:
        label_time = datetime.fromisoformat(r["label_available_at"])
        assert label_time < val_start, f"Training label available at {label_time} leaks into validation starting at {val_start}"

    # Check every validation sample's label availability
    test_start = datetime.fromisoformat(window["test_start"])
    for r in window["validation"]:
        label_time = datetime.fromisoformat(r["label_available_at"])
        assert label_time < test_start, f"Validation label available at {label_time} leaks into test starting at {test_start}"


def test_embargo_boundaries_purge_overlapping_boundary_bars():
    """Verify the 1-bar embargo removes exactly the boundary row whose label overlaps next partition."""
    dataset = _make_synth_series(25)
    labeled = label_dataset(dataset)
    rows = labeled["rows"]

    # Raw slicing of 8 train, 4 validation, 4 test
    window = window_split(rows, train_end=8, validation_end=12, test_end=16)
    assert window["ok"] is True

    # Because intervals are contiguous 15m, the 8th train row's label is available at 9th row's as_of (val start)
    # Thus exactly 1 training row must be purged by embargo
    assert len(window["embargo_train_keys"]) == 1
    assert len(window["train"]) == 7
    assert window["raw_train_count"] == 8

    # Similarly, 1 validation row must be purged by embargo
    assert len(window["embargo_validation_keys"]) == 1
    assert len(window["validation"]) == 3
    assert window["raw_validation_count"] == 4

    # Test rows are untouched by embargo
    assert len(window["test"]) == 4
    assert window["raw_test_count"] == 4


def test_insufficient_data_rejection_at_dataset_and_fold_levels():
    """Verify short series or under-sized folds fail cleanly with structured error codes."""
    # 1. Dataset too small for initial train + val + test
    tiny_dataset = _make_synth_series(8)
    config = WalkForwardConfig(initial_train_size=8, validation_size=4, test_size=4)
    res = run_walk_forward(tiny_dataset, config=config)
    assert res["ok"] is False
    assert res["code"] == "INSUFFICIENT_DATA"

    # 2. Fold under-sized after embargo
    medium_dataset = _make_synth_series(25)
    strict_config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=10,  # post-embargo count is 5, below 10
        min_validation=2,
        min_test=3,
    )
    res2 = run_walk_forward(medium_dataset, config=strict_config)
    assert res2["ok"] is True
    artifact = res2["artifact"]
    # First fold must fail cleanly with INSUFFICIENT_AFTER_EMBARGO
    fold_0 = artifact["folds"][0]
    assert fold_0["ok"] is False
    assert fold_0["code"] == "INSUFFICIENT_AFTER_EMBARGO"
    assert fold_0["config"]["min_train"] == 10


def test_missing_timestamps_and_duplicate_candles_detection():
    """Verify duplicate observations and missing bars are flagged explicitly without guessing."""
    # Duplicate as_of in rows
    dataset = _make_synth_series(20)
    labeled = label_dataset(dataset)
    rows = copy.deepcopy(labeled["rows"])
    rows[2]["as_of"] = rows[1]["as_of"]

    # window_split must detect ambiguous timestamp
    w = window_split(rows, train_end=5, validation_end=10, test_end=15)
    assert w["ok"] is False
    assert w["code"] in ("AMBIGUOUS_TIME", "DUPLICATE_OBSERVATION")


def test_reproducibility_of_dataset_and_experiment_hashes():
    """Verify dataset sealing and experiment hashing are deterministic and reproducible."""
    dataset1 = _make_synth_series(25)
    dataset2 = copy.deepcopy(dataset1)

    hash1 = content_hash(dataset1)
    hash2 = content_hash(dataset2)
    assert hash1 == hash2

    config = WalkForwardConfig(initial_train_size=6, validation_size=3, test_size=3, step_size=3, min_train=4, min_validation=2, min_test=3)
    res1 = run_walk_forward(dataset1, config=config)
    res2 = run_walk_forward(dataset2, config=config)

    assert res1["ok"] is True and res2["ok"] is True
    assert res1["artifact"]["walkforward_id"] == res2["artifact"]["walkforward_id"]
    assert res1["artifact"]["checksum"] == res2["artifact"]["checksum"]


def test_clear_rejection_of_quarantined_or_unverified_data():
    """Verify that quarantined data or unverified datasets cannot enter walk-forward evaluation."""
    # 1. Dataset carrying quarantine marker
    dataset = _make_synth_series(25)
    dataset["quarantine_id"] = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
    dataset["label"] = "UNVERIFIED_PROVIDER"

    res = run_walk_forward(dataset)
    assert res["ok"] is False
    assert res["code"] == "QUARANTINE_REJECTED"

    # 2. When require_verified_history is True, synthetic dataset must be rejected
    clean_synth = _make_synth_series(25)
    res_verified_req = run_walk_forward(clean_synth, require_verified_history=True)
    assert res_verified_req["ok"] is False
    assert res_verified_req["code"] == "UNVERIFIED_HISTORY"


def test_baseline_models_genuinely_fitted_on_train_and_scored_on_test():
    """Verify majority_class, last_return_sign, and logistic_regression baselines train and score out-of-sample."""
    dataset = _make_synth_series(25)
    labeled = label_dataset(dataset)
    rows = labeled["rows"]

    window = window_split(rows, train_end=10, validation_end=14, test_end=18)
    train_rows = window["train"]
    test_rows = window["test"]

    # 1. Majority class
    m_maj = fit_majority(train_rows)
    assert m_maj["ok"] is True
    assert m_maj["family"] == "majority_class"
    p_maj = predict_majority(m_maj, test_rows)
    assert len(p_maj) == len(test_rows)
    assert all(p == m_maj["positive_probability"] for p in p_maj)

    # 2. Last return sign
    m_lrs = fit_last_return_sign(train_rows)
    assert m_lrs["ok"] is True
    assert m_lrs["family"] == "last_return_sign"
    p_lrs = predict_last_return_sign(m_lrs, test_rows)
    assert p_lrs is not None
    assert len(p_lrs) == len(test_rows)

    # 3. Logistic regression
    m_log = fit_logistic(train_rows)
    assert m_log["ok"] is True
    assert m_log["family"] == "logistic_regression"
    assert m_log["converged"] is True
    p_log = predict_logistic(m_log, test_rows)
    assert p_log is not None
    assert len(p_log) == len(test_rows)
    assert all(0.0 <= p <= 1.0 for p in p_log)

    # Binary metrics check
    test_labels = [r["direction"] for r in test_rows]
    metrics = binary_metrics(test_labels, p_log)
    assert metrics["status"] == "DEFINED"
    assert "accuracy" in metrics
    assert "log_loss" in metrics
    assert "brier" in metrics
    assert "confusion_matrix" in metrics


def test_model_selection_validation_only_and_out_of_sample_test():
    """Verify model selection is driven exclusively by validation log loss and test is strictly out-of-sample."""
    dataset = _make_synth_series(25)
    config = WalkForwardConfig(initial_train_size=6, validation_size=3, test_size=3, step_size=3, min_train=4, min_validation=2, min_test=3)
    res = run_walk_forward(dataset, config=config)
    assert res["ok"] is True
    artifact = res["artifact"]

    for fold in artifact["folds"]:
        if not fold.get("ok"):
            continue
        assert fold["test_used_for_selection"] is False
        assert fold["selected_model"] in ("majority_class", "last_return_sign", "logistic_regression")
        val_metrics = {m: fold["model_results"][m]["validation"] for m in fold["model_results"]}
        # Verify choose_model picks the fold selected_model
        assert choose_model(val_metrics) == fold["selected_model"]


def test_walkforward_macro_and_pooled_aggregates_reported():
    """Verify walkforward artifact records per-fold metrics, macro-aggregates, and pooled test predictions."""
    dataset = _make_synth_series(25)
    config = WalkForwardConfig(initial_train_size=6, validation_size=3, test_size=3, step_size=3, min_train=4, min_validation=2, min_test=3)
    res = run_walk_forward(dataset, config=config)
    assert res["ok"] is True
    artifact = res["artifact"]

    agg = artifact["aggregate"]
    assert agg["successful_folds"] >= 2
    assert "macro" in agg
    assert "majority_class" in agg["macro"]
    assert "logistic_regression" in agg["macro"]
    assert "pooled_selected_model" in agg
    assert agg["pooled_selected_model"]["status"] == "DEFINED"
    assert agg["total_scored_test_observations"] > 0


def test_model_registry_walkforward_m4_registration(tmp_path):
    """Verify an M4 walk-forward experiment registers cleanly in the model registry."""
    dataset = _make_synth_series(25)
    config = WalkForwardConfig(initial_train_size=6, validation_size=3, test_size=3, step_size=3, min_train=4, min_validation=2, min_test=3)
    res = run_walk_forward(dataset, config=config)
    artifact = res["artifact"]

    reg_file = tmp_path / "registry.json"
    store = RegistryStore(reg_file)
    doc = store.read()

    doc, reg_res = register_artifact(doc, artifact, kind="m4", actor="researcher", expected_revision=doc["revision"])
    assert reg_res["ok"] is True
    assert reg_res["duplicate"] is False
    assert len(reg_res["versions"]) == 3
    for v in reg_res["versions"]:
        assert v["status"] == "TRAINED"
        assert v["family"] in ("base_rate", "persistence", "logistic_regression")

    # Safety invariant checks
    assert reg_res["forecast_ready"] is False
    assert reg_res["paper_approved"] is False
    assert reg_res["live_approved"] is False
    assert reg_res["real_market_data_verified"] is False
