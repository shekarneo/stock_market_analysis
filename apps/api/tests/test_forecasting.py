from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

import pytest

from app.features.pipeline import build_dataset
from app.forecasting.experiment import choose_model, run_experiment, score_saved_logistic, training_scaler_means
from app.forecasting.metrics import binary_metrics
from app.forecasting.models import (
    _reject_step,
    fit_last_return_sign,
    fit_logistic,
    fit_majority,
    predict_last_return_sign,
    predict_majority,
)
from app.forecasting.splits import SplitConfig, chronological_split
from app.forecasting.store import ExperimentStore, ExperimentStoreError
from app.forecasting.targets import MODEL_FEATURES, label_dataset
from app.market.fixtures import fixture_calendar, quiet_day_candles
from app.market.schemas import IST, Candle, DataOrigin, MarketSession

RETRIEVED = datetime(2026, 1, 5, 15, 30, tzinfo=IST)
SMALL = SplitConfig(min_train=6, min_validation=2, min_test=3)


def series(closes: list[float], *, origin: DataOrigin = DataOrigin.SYNTHETIC, source_id: str = "unit") -> dict:
    start = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    candles = []
    for step, close in enumerate(closes):
        bar_start = start + timedelta(minutes=15 * step)
        candles.append(
            Candle(
                instrument_id="NIFTY",
                underlying="NIFTY",
                exchange=None,
                interval="M15",
                bar_start=bar_start,
                bar_end=bar_start + timedelta(minutes=15),
                provider_timestamp=None,
                retrieved_at=RETRIEVED,
                open=close,
                high=close + 2,
                low=close - 2,
                close=close,
                volume=None,
                source_id=source_id,
                origin=origin,
                session=MarketSession.OPEN,
            )
        )
    built = build_dataset(candles, fixture_calendar())
    assert built.ok, built
    return built.artifact


def alternating(flat_at: int | None = None) -> list[float]:
    price = 1000.0
    closes = []
    for index in range(25):
        closes.append(price)
        if flat_at is not None and index == flat_at:
            continue
        price += 2 if index % 2 == 0 else -1
    return closes


def test_target_formula_zero_class_and_final_bar_have_no_fabricated_label():
    artifact = series(alternating(flat_at=10))
    labeled = label_dataset(artifact)
    assert labeled["ok"] is True
    assert labeled["target_id"] == "m15_next_close_direction"
    assert labeled["target_version"] == "binary-1"
    assert labeled["zero_return_count"] == 1
    assert labeled["zero_return_share"] == pytest.approx(1 / labeled["rows_with_future_candle"])
    flat = next(row for row in labeled["rows"] if row["future_return"] == 0)
    assert flat["direction"] == 0
    assert labeled["exclusion_reasons"]["NO_FUTURE_CANDLE"] == 1
    assert all(row["as_of"] < row["label_available_at"] for row in labeled["rows"])
    assert artifact["rows"][-1]["as_of"] not in {row["as_of"] for row in labeled["rows"]}


def test_label_uses_the_next_close_and_not_the_close_after_that():
    base = alternating()
    original = series(base)
    labeled = label_dataset(original)
    target = labeled["rows"][0]
    next_close = base[6]
    later_close = base[7]
    changed_next = base[:]
    changed_next[6] = next_close + 50
    relabeled = label_dataset(series(changed_next))
    moved = next(row for row in relabeled["rows"] if row["as_of"] == target["as_of"])
    assert moved["features"] == target["features"]
    assert moved["future_return"] != target["future_return"]
    changed_later = base[:]
    changed_later[7] = later_close + 50
    held = label_dataset(series(changed_later))
    held_row = next(row for row in held["rows"] if row["as_of"] == target["as_of"])
    assert held_row["future_return"] == target["future_return"]
    assert held_row["features"] == target["features"]


def test_incomplete_future_candle_is_excluded():
    payload = _hand_candles([100, 110, 120, 130])
    future = payload["source_candles"][1]
    future_end = future["bar_end"]
    future["retrieved_at"] = "2026-01-05T09:00:00+05:30"
    labeled = label_dataset(payload)
    assert labeled["exclusion_reasons"].get("INCOMPLETE_FUTURE_CANDLE", 0) >= 1
    assert all(row["label_available_at"] != future_end for row in labeled["rows"])


def test_synthetic_and_documented_sample_cannot_claim_market_performance():
    synthetic = label_dataset(series(alternating()))
    assert synthetic["synthetic"] is True
    assert synthetic["real_market_eligible"] is False
    assert synthetic["performance_claim_allowed"] is False
    assert synthetic["forecast_ready"] is False
    sample = label_dataset(series(alternating(), origin=DataOrigin.DOCUMENTED_SAMPLE, source_id="doc"))
    assert sample["origin"] == "DOCUMENTED_SAMPLE"
    assert sample["synthetic"] is False
    assert sample["real_market_eligible"] is False
    provider = label_dataset(series(alternating(), origin=DataOrigin.PROVIDER, source_id="provider"))
    assert provider["real_market_eligible"] is True
    assert provider["real_market_data_verified"] is False
    assert provider["performance_claim_allowed"] is False


def test_split_is_chronological_and_ignores_input_order():
    labeled = label_dataset(series(alternating()))
    forward = chronological_split(labeled["rows"], SMALL)
    backward = chronological_split(list(reversed(labeled["rows"])), SMALL)
    assert forward["shuffled"] is False
    assert [row["as_of"] for row in forward["train"]] == [row["as_of"] for row in backward["train"]]
    assert forward["train"][-1]["as_of"] < forward["validation"][0]["as_of"] < forward["test"][0]["as_of"]
    validation_start = forward["validation"][0]["as_of"]
    assert all(row["label_available_at"] < validation_start for row in forward["train"])
    assert forward["embargo_train"] >= 1


def test_default_split_refuses_a_short_series_without_inventing_rows():
    quiet = build_dataset(quiet_day_candles("NIFTY", retrieved_at=RETRIEVED), fixture_calendar())
    result = run_experiment(quiet.artifact)
    assert result["ok"] is False
    assert result["code"] == "INSUFFICIENT_DATA"
    assert result["artifact"] is None
    assert result["forecast_ready"] is False
    assert result["eligibility"]["eligible_observations"] < 8


def test_baselines_do_not_read_future_labels_and_logistic_rejects_one_class():
    artifact = series(alternating())
    labeled = label_dataset(artifact)
    split = chronological_split(labeled["rows"], SMALL)
    majority = fit_majority(split["train"])
    poisoned = [dict(row, direction=0) for row in split["validation"]]
    assert predict_majority(majority, poisoned) == predict_majority(majority, split["validation"])
    assert majority["positive_probability"] == pytest.approx(
        sum(row["direction"] for row in split["train"]) / len(split["train"])
    )
    sign_model = fit_last_return_sign(split["train"])
    same_sign = {
        "features": {"ret_1": 0.1},
        "direction": 0,
    }
    other = {"features": {"ret_1": 0.1}, "direction": 1}
    assert predict_last_return_sign(sign_model, [same_sign]) == predict_last_return_sign(sign_model, [other])
    unavailable = fit_last_return_sign([{"features": {"ret_1": None}, "direction": 1}])
    assert unavailable["ok"] is False
    assert unavailable["code"] == "PREVIOUS_DIRECTION_UNAVAILABLE"
    rising = series([1000 + index for index in range(25)])
    single = run_experiment(rising, config=SMALL)
    assert single["ok"] is True
    assert single["artifact"]["models"]["logistic_regression"]["code"] == "SINGLE_CLASS"
    assert "logistic_regression" not in single["artifact"]["validation_metrics"]


def test_scaler_uses_training_rows_only():
    result = run_experiment(series(alternating()), config=SMALL)
    artifact = result["artifact"]
    labeled = label_dataset(series(alternating()))
    split = chronological_split(labeled["rows"], SMALL)
    means = training_scaler_means(split["train"])
    assert artifact["models"]["logistic_regression"]["scaler"]["means"] == pytest.approx(means)
    contaminated = training_scaler_means(split["train"] + split["test"])
    assert contaminated != pytest.approx(means)


def test_metrics_match_a_known_table_and_keep_undefined_values_null():
    labels = [1, 0, 1, 0]
    probabilities = [0.8, 0.2, 0.6, 0.7]
    report = binary_metrics(labels, probabilities)
    assert report["observations"] == 4
    assert report["positive_class"] == 1
    assert report["positive_prevalence"] == pytest.approx(0.5)
    assert report["accuracy"]["value"] == pytest.approx(0.75)
    assert report["precision"]["value"] == pytest.approx(2 / 3)
    assert report["recall"]["value"] == pytest.approx(1)
    assert report["f1"]["value"] == pytest.approx(0.8)
    assert report["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 0, "tp": 2}
    expected_brier = ((0.8 - 1) ** 2 + (0.2 - 0) ** 2 + (0.6 - 1) ** 2 + (0.7 - 0) ** 2) / 4
    assert report["brier"]["value"] == pytest.approx(expected_brier)
    clipped = [min(1 - 1e-15, max(1e-15, probability)) for probability in probabilities]
    expected_loss = -sum(
        label * math.log(probability) + (1 - label) * math.log(1 - probability)
        for label, probability in zip(labels, clipped)
    ) / 4
    assert report["log_loss"]["value"] == pytest.approx(expected_loss)
    assert report["probabilities_are_calibrated"] is False
    assert report["calibration"]["status"] == "INSUFFICIENT_OBSERVATIONS"
    undefined = binary_metrics([1, 0], [0.1, 0.2])
    assert undefined["precision"]["value"] is None
    assert undefined["precision"]["status"] == "UNDEFINED_NO_PREDICTED_POSITIVE"
    missing_class = binary_metrics([1, 1], [0.9, 0.8])
    assert missing_class["balanced_accuracy"]["value"] is None
    invalid = binary_metrics([1], [1.2])
    assert invalid["log_loss"]["value"] is None


def test_selection_uses_log_loss_not_accuracy_and_test_labels_do_not_change_it():
    chosen = choose_model(
        {
            "majority_class": {"log_loss": {"value": 0.2}, "brier": {"value": 0.2}, "accuracy": {"value": 0.4}},
            "last_return_sign": {"log_loss": {"value": 0.9}, "brier": {"value": 0.1}, "accuracy": {"value": 0.9}},
        }
    )
    assert chosen == "majority_class"
    first = run_experiment(series(alternating()), config=SMALL)
    closes = alternating()
    closes[-1] += 40
    second = run_experiment(series(closes), config=SMALL)
    assert first["artifact"]["selected_model"] == second["artifact"]["selected_model"]
    assert first["artifact"]["validation_metrics"] == second["artifact"]["validation_metrics"]
    assert first["artifact"]["selection_metric"] == "log_loss"
    assert first["artifact"]["selected_model"] == choose_model(first["artifact"]["validation_metrics"])
    assert first["artifact"]["selection_inputs"] == ["validation_log_loss", "validation_brier", "model_name"]
    assert first["artifact"]["test_used_for_selection"] is False
    assert first["artifact"]["models"]["logistic_regression"]["threshold"] == 0.5
    assert "test_metrics" not in first["artifact"]["selection_inputs"]


def test_experiment_artifact_is_reproducible_and_not_forecast_ready(tmp_path):
    dataset = series(alternating())
    first = run_experiment(dataset, config=SMALL)
    second = run_experiment(dataset, config=SMALL)
    assert first["ok"] is True
    assert first["forecast_ready"] is False
    artifact = first["artifact"]
    assert artifact["experiment_id"] == second["artifact"]["experiment_id"]
    assert artifact["checksum"] == artifact["experiment_id"]
    assert artifact["training_dataset_id"] == dataset["dataset_id"]
    assert artifact["evaluation_version"] == "m3-holdout-1"
    assert artifact["identity_excludes_write_time"] is True
    assert "written_at" not in artifact
    assert artifact["models"]["logistic_regression"]["converged"] is True
    assert artifact["split"]["embargo_rule"]
    assert artifact["origin"] == "SYNTHETIC"
    assert artifact["target_version"] == "binary-1"
    assert artifact["feature_set_version"] == "ohlc-1"
    assert artifact["approved_for_live"] is False
    assert artifact["production_approved"] is False
    assert artifact["readiness"]["forecast_ready"] is False
    assert artifact["readiness"]["real_market_data_verified"] is False
    assert "REAL_MARKET_DATA_NOT_VERIFIED" in artifact["readiness"]["unmet_requirements"]
    other = run_experiment(series([1000 + (index % 5) for index in range(25)]), config=SMALL)
    assert other["artifact"]["experiment_id"] != artifact["experiment_id"]
    shared = set(artifact["validation_metrics"])
    counts = {name: artifact["validation_metrics"][name]["observations"] for name in shared}
    assert len(set(counts.values())) == 1
    for report in artifact["test_metrics"].values():
        for probability_report in (report,):
            assert probability_report["positive_class"] == 1
    store = ExperimentStore(tmp_path)
    store.write(artifact)
    assert store.read(artifact["experiment_id"])["checksum"] == artifact["checksum"]
    path = tmp_path / f"{artifact['experiment_id']}.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["selected_model"] = "tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ExperimentStoreError) as caught:
        store.read(artifact["experiment_id"])
    assert caught.value.code == "CHECKSUM_MISMATCH"
    scored = score_saved_logistic(second["artifact"], label_dataset(dataset)["rows"][:2])
    assert scored["ok"] is True
    assert scored["forecast_ready"] is False
    assert all(0 <= probability <= 1 for probability in scored["probabilities"])
    unsafe = dict(artifact)
    unsafe["path"] = "/tmp/outside.json"
    with pytest.raises(ExperimentStoreError) as unsafe_path:
        store.write(unsafe)
    assert unsafe_path.value.code == "UNSAFE_PATH"
    with pytest.raises(ExperimentStoreError):
        store.read("../etc/passwd")


def test_version_and_checksum_guards():
    dataset = series(alternating())
    mismatch = run_experiment(dataset, config=SMALL, target_version="binary-2")
    assert mismatch["ok"] is False
    assert mismatch["code"] == "TARGET_VERSION_MISMATCH"
    assert mismatch["forecast_ready"] is False
    broken = dict(dataset)
    broken["feature_set_version"] = "ohlc-2"
    assert label_dataset(broken)["code"] == "CHECKSUM_MISMATCH"
    unsigned = _hand_candles([100, 110])
    unsigned["feature_set_version"] = "ohlc-2"
    assert label_dataset(unsigned)["code"] == "FEATURE_VERSION_MISMATCH"
    dataset["rows"][0]["values"]["ret_1"]["value"] = 123
    assert run_experiment(dataset, config=SMALL)["code"] == "CHECKSUM_MISMATCH"


def _hand_candles(closes: list[float]) -> dict:
    start = datetime(2026, 1, 5, 10, 0, tzinfo=IST)
    candles = []
    rows = []
    for index, close in enumerate(closes):
        bar_start = start + timedelta(minutes=15 * index)
        bar_end = bar_start + timedelta(minutes=15)
        candles.append(
            {
                "bar_start": bar_start.isoformat(),
                "bar_end": bar_end.isoformat(),
                "retrieved_at": datetime(2026, 1, 5, 15, 30, tzinfo=IST).isoformat(),
                "close": close,
            }
        )
        values = {name: {"value": 0.01 * (index + 1), "status": "VALID"} for name in MODEL_FEATURES}
        rows.append(
            {
                "instrument_id": "NIFTY",
                "as_of": bar_end.isoformat(),
                "origin": "SYNTHETIC",
                "values": values,
            }
        )
    return {
        "feature_set_version": "ohlc-1",
        "interval": "M15",
        "forecast_ready": False,
        "dataset_id": "hand",
        "created_at": candles[-1]["retrieved_at"],
        "origin": "SYNTHETIC",
        "source_id": "hand",
        "instrument_id": "NIFTY",
        "start": candles[0]["bar_start"],
        "end": candles[-1]["bar_end"],
        "source_candles": candles,
        "rows": rows,
    }


def test_hand_labels_use_only_the_next_completed_close():
    labeled = label_dataset(_hand_candles([100, 110, 110, 90]))
    assert [row["direction"] for row in labeled["rows"]] == [1, 0, 0]
    assert labeled["rows"][0]["future_return"] == pytest.approx(0.1)
    assert labeled["rows"][1]["future_return"] == 0
    assert labeled["zero_return_count"] == 1
    assert labeled["exclusion_reasons"]["NO_FUTURE_CANDLE"] == 1
    assert set(labeled["rows"][0]["features"]) == set(MODEL_FEATURES)
    assert "future_close" not in labeled["rows"][0]
    changed = _hand_candles([100, 110, 110, 90])
    changed["source_candles"][3]["close"] = 200
    relabeled = label_dataset(changed)
    assert relabeled["rows"][0]["future_return"] == labeled["rows"][0]["future_return"]
    assert relabeled["rows"][0]["features"] == labeled["rows"][0]["features"]
    assert relabeled["rows"][2]["direction"] == 1


def test_embargo_removes_the_boundary_label_rows():
    start = datetime(2026, 1, 5, 10, 0, tzinfo=IST)
    rows = []
    for index in range(8):
        as_of = start + timedelta(minutes=15 * (index + 1))
        rows.append(
            {
                "key": f"NIFTY|{as_of.isoformat()}",
                "as_of": as_of.isoformat(),
                "label_available_at": (as_of + timedelta(minutes=15)).isoformat(),
                "direction": index % 2,
                "features": {"ret_1": 0.1},
            }
        )
    split = chronological_split(rows, SplitConfig(train_fraction=0.5, validation_fraction=0.25, min_train=3, min_validation=1, min_test=2))
    assert split["ok"] is True
    assert split["manifest"]["embargo_train_keys"] == [rows[3]["key"]]
    assert split["manifest"]["embargo_validation_keys"] == [rows[5]["key"]]
    validation_start = split["validation"][0]["as_of"]
    test_start = split["test"][0]["as_of"]
    assert all(row["label_available_at"] < validation_start for row in split["train"])
    assert all(row["label_available_at"] < test_start for row in split["train"] + split["validation"])
    assert rows[3]["label_available_at"] == rows[4]["as_of"]
    assert rows[5]["label_available_at"] == rows[6]["as_of"]


def test_selection_tolerance_and_test_scores_are_not_the_inputs():
    chosen = choose_model(
        {
            "majority_class": {"log_loss": {"value": 0.5}, "brier": {"value": 0.2}},
            "last_return_sign": {"log_loss": {"value": 0.5 + 1e-15}, "brier": {"value": 0.2}},
        }
    )
    assert chosen == "last_return_sign"
    validation = {"majority_class": {"log_loss": {"value": 0.2}, "brier": {"value": 0.2}}}
    test_scores = {"majority_class": {"log_loss": {"value": 0.9}, "brier": {"value": 0.1}}}
    assert choose_model(validation) == "majority_class"
    assert choose_model(test_scores) == "majority_class"


def _feature_row(direction: int, **overrides: float) -> dict:
    features = {name: 0.0 for name in MODEL_FEATURES}
    features.update(overrides)
    return {"direction": direction, "features": features}


def test_logistic_constant_features_single_class_and_failed_steps():
    constant = fit_logistic([_feature_row(0), _feature_row(1), _feature_row(0), _feature_row(1)])
    assert constant["ok"] is True
    assert constant["converged"] is True
    assert set(constant["scaler"]["zero_variance"]) == set(MODEL_FEATURES)
    assert all(math.isfinite(weight) for weight in constant["weights"])
    single = fit_logistic([_feature_row(1, ret_1=0.2), _feature_row(1, ret_1=-0.2)])
    assert single["code"] == "SINGLE_CLASS"
    invalid = fit_logistic([_feature_row(0, ret_1=math.nan), _feature_row(1, ret_1=0.2)])
    assert invalid["code"] == "INVALID_FEATURE"
    unfinished = fit_logistic(
        [_feature_row(0, ret_1=-0.2), _feature_row(1, ret_1=0.4), _feature_row(0, ret_1=-0.1), _feature_row(1, ret_1=0.3)],
        max_iter=1,
    )
    assert unfinished["code"] == "NON_CONVERGED"
    singular = fit_logistic([_feature_row(0), _feature_row(1), _feature_row(0), _feature_row(1)], l2=0)
    assert singular["code"] == "SINGULAR_HESSIAN"
    assert _reject_step([1e7]) == "ILL_CONDITIONED"
    assert _reject_step([math.nan]) == "INVALID_FIT"
