from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.forecasting.experiment import _alignment_error, _score_all
from app.forecasting.splits import window_split
from app.forecasting.store import ExperimentStoreError, WalkForwardStore
from app.forecasting.targets import MODEL_FEATURES, label_dataset
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward
from app.market.schemas import IST, DataOrigin
from tests.test_forecasting import alternating, series

from fastapi.testclient import TestClient


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row(as_of: str, label_at: str, direction: int, ret_1: float) -> dict:
    features = {name: 0.0 for name in MODEL_FEATURES}
    features["ret_1"] = ret_1
    features["close_vs_sma_5"] = ret_1
    return {
        "key": f"NIFTY|{as_of}",
        "instrument_id": "NIFTY",
        "as_of": as_of,
        "label_available_at": label_at,
        "direction": direction,
        "origin": "SYNTHETIC",
        "features": features,
    }


def _stamp(minute_offset: int, *, offset: str = "+05:30") -> str:
    moment = datetime(2026, 1, 5, 10, 0, tzinfo=IST) + timedelta(minutes=minute_offset)
    if offset == "+00:00":
        moment = moment.astimezone(timedelta_utc())
    return moment.isoformat()


def timedelta_utc():
    from datetime import timezone

    return timezone.utc


def _contiguous(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        as_of = _stamp(15 * index)
        label_at = _stamp(15 * (index + 1))
        direction = index % 2
        rows.append(_row(as_of, label_at, direction, 0.01 if direction == 0 else -0.01))
    return rows


def _assert_no_label_leak(window: dict) -> None:
    validation_times = [_parse(row["as_of"]) for row in window["validation"]]
    test_times = [_parse(row["as_of"]) for row in window["test"]]
    assert window["train"]
    assert window["validation"]
    assert window["test"]
    for row in (window["train"][0], window["train"][-1], *window["train"]):
        label_at = _parse(row["label_available_at"])
        assert _parse(row["as_of"]) < label_at
        assert label_at < min(validation_times)
        assert all(label_at < moment for moment in test_times)
    for row in (window["validation"][0], window["validation"][-1], *window["validation"]):
        label_at = _parse(row["label_available_at"])
        assert _parse(row["as_of"]) < label_at
        assert all(label_at < moment for moment in test_times)
    for row in (window["test"][0], window["test"][-1], *window["test"]):
        assert _parse(row["as_of"]) < _parse(row["label_available_at"])


def test_window_split_sorts_and_keeps_fixed_sizes_without_shuffle():
    rows = list(reversed(_contiguous(12)))
    window = window_split(rows, train_end=6, validation_end=9, test_end=12)
    assert window["ok"] is True
    assert window["shuffled"] is False
    assert window["raw_train_count"] == 6
    assert window["raw_validation_count"] == 3
    assert window["raw_test_count"] == 3
    assert _parse(window["train_start"]) < _parse(window["train_end"])
    assert _parse(window["train_end"]) < _parse(window["validation_start"])
    assert _parse(window["validation_end"]) < _parse(window["test_start"])
    _assert_no_label_leak(window)


def test_embargo_uses_label_time_across_a_missing_interval_and_not_only_the_previous_index():
    rows = [
        _row(_stamp(0), _stamp(15), 1, 0.02),
        _row(_stamp(15), _stamp(60), 0, -0.01),
        _row(_stamp(60), _stamp(75), 1, 0.02),
        _row(_stamp(75), _stamp(90), 0, -0.01),
        _row(_stamp(90), _stamp(105), 1, 0.03),
        _row(_stamp(105), _stamp(120), 0, -0.02),
    ]
    window = window_split(rows, train_end=2, validation_end=4, test_end=6)
    assert window["ok"] is True
    assert rows[1]["key"] in window["embargo_train_keys"]
    assert rows[0]["key"] not in window["embargo_train_keys"]
    assert _parse(window["train"][0]["label_available_at"]) < _parse(window["validation_start"])
    assert _parse(rows[1]["label_available_at"]) == _parse(window["validation_start"])
    assert rows[3]["key"] in window["embargo_validation_keys"]
    _assert_no_label_leak(window)
    assert _alignment_error(window) is None


def test_timezone_equivalent_label_is_embargoed():
    same_instant = "2026-01-05T05:30:00+00:00"
    earlier = "2026-01-05T05:15:00+00:00"
    rows = [
        _row(_stamp(0), earlier, 1, 0.02),
        _row(_stamp(15), same_instant, 0, -0.01),
        _row(_stamp(60), _stamp(75), 1, 0.02),
        _row(_stamp(75), _stamp(90), 0, -0.01),
        _row(_stamp(90), _stamp(105), 1, 0.01),
        _row(_stamp(105), _stamp(120), 0, -0.02),
    ]
    assert same_instant < _stamp(60)
    window = window_split(rows, train_end=2, validation_end=4, test_end=6)
    assert rows[1]["key"] in window["embargo_train_keys"]
    assert rows[0]["key"] not in window["embargo_train_keys"]
    assert _parse(rows[1]["label_available_at"]) == _parse(window["validation_start"])
    _assert_no_label_leak(window)


def test_equal_timestamps_are_rejected():
    rows = _contiguous(6)
    rows[2]["as_of"] = rows[1]["as_of"]
    rows[2]["key"] = "NIFTY|other"
    window = window_split(rows, train_end=2, validation_end=4, test_end=6)
    assert window["ok"] is False
    assert window["code"] == "AMBIGUOUS_TIME"


def test_expanding_folds_keep_fixed_validation_and_test_and_do_not_shrink_minimums():
    dataset = series(alternating())
    dataset_id = dataset["dataset_id"]
    before = json.dumps(dataset, sort_keys=True)
    config = WalkForwardConfig(
        initial_train_size=4,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=8,
        min_validation=2,
        min_test=3,
    )
    result = run_walk_forward(dataset, config=config)
    assert json.dumps(dataset, sort_keys=True) == before
    assert dataset["dataset_id"] == dataset_id
    assert result["ok"] is True
    artifact = result["artifact"]
    folds = artifact["folds"]
    assert folds[0]["ok"] is False
    assert folds[0]["code"] == "INSUFFICIENT_AFTER_EMBARGO"
    assert folds[0]["raw_train_count"] == 4
    assert folds[0]["config"]["min_train"] == 8
    assert [fold["train_end_index"] for fold in folds] == [4, 7, 10, 13]
    assert {fold["raw_validation_count"] for fold in folds} == {3}
    assert {fold["raw_test_count"] for fold in folds} == {3}
    assert folds[0]["train_start"] == folds[-1]["train_start"]
    assert _parse(folds[0]["train_end"]) < _parse(folds[-1]["train_end"])
    labeled = label_dataset(dataset)["rows"]
    for fold in folds:
        if not fold["ok"]:
            continue
        window = window_split(
            labeled,
            train_end=fold["train_end_index"],
            validation_end=fold["validation_end_index"],
            test_end=fold["test_end_index"],
        )
        _assert_no_label_leak(window)
        assert fold["embargo_train_keys"] == window["embargo_train_keys"]
        assert fold["embargo_validation_keys"] == window["embargo_validation_keys"]
    assert artifact["successful_folds"] >= 1
    assert artifact["failed_folds"] >= 1
    assert artifact["forecast_ready"] is False


def test_successful_folds_select_on_validation_and_keep_test_scores_separate():
    dataset = series(alternating())
    config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=4,
        min_validation=2,
        min_test=3,
    )
    artifact = run_walk_forward(dataset, config=config)["artifact"]
    assert artifact["successful_folds"] == 3
    assert artifact["failed_folds"] == 0
    labeled = label_dataset(dataset)["rows"]
    for fold in artifact["folds"]:
        assert fold["test_used_for_selection"] is False
        assert set(fold["model_results"]) == {"majority_class", "last_return_sign", "logistic_regression"}
        selected = fold["selected_model_result"]
        assert selected["test"] == fold["model_results"][fold["selected_model"]]["test"]
        assert selected["validation"]["log_loss"]["value"] is not None
        window = window_split(
            labeled,
            train_end=fold["train_end_index"],
            validation_end=fold["validation_end_index"],
            test_end=fold["test_end_index"],
        )
        _assert_no_label_leak(window)
        assert fold["selected_model_result"]["test"]["observations"] == len(window["test"])
        assert fold["selected_model_result"]["validation"]["observations"] == len(window["validation"])
        assert fold["selected_model_result"]["test"]["probabilities_are_calibrated"] is False
    scored = sum(fold["eligible_test_count"] for fold in artifact["folds"])
    assert artifact["aggregate"]["total_scored_test_observations"] == scored
    assert artifact["aggregate"]["pooled_selected_model"]["observations"] == scored
    assert "confusion_matrix" in artifact["aggregate"]["pooled_selected_model"]
    assert "mean_confusion_matrix" not in artifact["aggregate"]
    notes = artifact["aggregate"]["aggregation_notes"]
    assert "equal weight" in notes["macro"]
    assert artifact["selection_counts"][artifact["folds"][0]["selected_model"]] >= 1
    one = run_walk_forward(
        dataset,
        config=WalkForwardConfig(
            initial_train_size=8,
            validation_size=4,
            test_size=4,
            step_size=4,
            min_train=6,
            min_validation=2,
            min_test=4,
        ),
    )["artifact"]
    assert one["successful_folds"] == 1
    one_accuracy = one["aggregate"]["macro_selected_model"]["accuracy"]
    assert one_accuracy["mean"] is not None
    assert one_accuracy["stdev"] is None
    assert one_accuracy["status"] == "UNDEFINED_SINGLE_FOLD_STDEV"


def test_single_class_logistic_is_recorded_and_not_replaced(monkeypatch):
    dataset = series([1000.0 + index for index in range(25)])
    config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=4,
        min_validation=2,
        min_test=3,
    )
    artifact = run_walk_forward(dataset, config=config)["artifact"]
    fold = artifact["folds"][0]
    assert fold["model_results"]["logistic_regression"]["failure"] == "SINGLE_CLASS"
    assert fold["model_results"]["logistic_regression"]["validation"] is None
    assert fold["selected_model"] != "logistic_regression"
    assert fold["selected_model"] in {"majority_class", "last_return_sign"}
    balanced = artifact["aggregate"]["macro_selected_model"]["balanced_accuracy"]
    assert balanced["mean"] is None
    assert balanced["contributing_folds"] == 0
    assert balanced["status"] == "UNDEFINED"
    accuracy = artifact["aggregate"]["macro_selected_model"]["accuracy"]
    assert accuracy["mean"] == pytest.approx(1.0)
    assert accuracy["stdev"] == pytest.approx(0.0)


def test_metric_row_mismatch_does_not_select(monkeypatch):
    def diverge(models, rows):
        reports = _score_all(models, rows)
        name = next(iter(reports))
        reports[name] = {**reports[name], "observations": reports[name]["observations"] + 1}
        return reports

    monkeypatch.setattr("app.forecasting.walkforward._score_all", diverge)
    dataset = series(alternating())
    config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=4,
        min_validation=2,
        min_test=3,
    )
    artifact = run_walk_forward(dataset, config=config)["artifact"]
    assert artifact["successful_folds"] == 0
    assert {fold["code"] for fold in artifact["folds"]} == {"METRIC_ROW_MISMATCH"}
    assert all(fold.get("selected_model") is None for fold in artifact["folds"])
    assert artifact["aggregate"]["pooled_selected_model"]["status"] == "NO_OBSERVATIONS"
    assert artifact["forecast_ready"] is False


def test_short_series_and_overlapping_step_do_not_emit_an_artifact():
    short = run_walk_forward(series(alternating()[:8]))
    assert short["ok"] is False
    assert short["code"] == "INSUFFICIENT_DATA"
    assert short["artifact"] is None
    assert short["forecast_ready"] is False
    overlap = run_walk_forward(
        series(alternating()),
        config=WalkForwardConfig(step_size=1, test_size=4, min_train=4, min_validation=2, min_test=2),
    )
    assert overlap["code"] == "OVERLAPPING_TEST"
    assert overlap["artifact"] is None
    embargo = run_walk_forward(series(alternating()), config=WalkForwardConfig(embargo_bars=2, min_train=4, min_validation=2, min_test=2))
    assert embargo["code"] == "UNSUPPORTED_EMBARGO"


def test_artifact_identity_integrity_and_provenance(tmp_path):
    dataset = series(alternating(), origin=DataOrigin.DOCUMENTED_SAMPLE, source_id="sample")
    config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=4,
        min_validation=2,
        min_test=3,
    )
    first = run_walk_forward(dataset, config=config)["artifact"]
    second = run_walk_forward(dataset, config=config)["artifact"]
    assert first["walkforward_id"] == second["walkforward_id"]
    assert first["checksum"] == first["walkforward_id"]
    assert first["dataset_checksum"] == dataset["checksum"]
    assert first["created_at"] == dataset["created_at"]
    assert first["identity_excludes_write_time"] is True
    assert "written_at" not in first
    assert first["origin"] == "DOCUMENTED_SAMPLE"
    assert first["synthetic"] is False
    assert first["documented_sample"] is True
    assert first["performance_claim_allowed"] is False
    assert first["forecast_ready"] is False
    assert first["paper_approved"] is False
    assert first["live_approved"] is False
    assert first["real_market_data_verified"] is False
    assert first["readiness"]["forecast_ready"] is False
    assert first["readiness"]["real_market_data_verified"] is False
    store = WalkForwardStore(tmp_path)
    store.write(first)
    assert store.read(first["walkforward_id"])["walkforward_id"] == first["walkforward_id"]
    tampered = json.loads(json.dumps(first))
    tampered["selected_model"] = "tampered"
    (tmp_path / f"{first['walkforward_id']}.json").write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ExperimentStoreError) as caught:
        store.read(first["walkforward_id"])
    assert caught.value.code == "CHECKSUM_MISMATCH"
    unsafe = json.loads(json.dumps(first))
    unsafe["path"] = "/tmp/outside.json"
    with pytest.raises(ExperimentStoreError) as refused:
        store.write(unsafe)
    assert refused.value.code == "UNSAFE_PATH"


def test_provider_origin_is_not_verified_market_data():
    dataset = series(alternating(), origin=DataOrigin.PROVIDER, source_id="provider-unverified")
    config = WalkForwardConfig(
        initial_train_size=6,
        validation_size=3,
        test_size=3,
        step_size=3,
        min_train=4,
        min_validation=2,
        min_test=3,
    )
    artifact = run_walk_forward(dataset, config=config)["artifact"]
    assert artifact["origin"] == "PROVIDER"
    assert artifact["eligibility"]["real_market_eligible"] is True
    assert artifact["real_market_data_verified"] is False
    assert artifact["performance_claim_allowed"] is False
    assert artifact["forecast_ready"] is False
    assert artifact["paper_approved"] is False
    assert artifact["live_approved"] is False


def test_naive_timestamp_that_reaches_a_fold_is_rejected(monkeypatch):
    dataset = series(alternating())

    def naive(artifact):
        labeled = label_dataset(artifact)
        labeled["rows"][0]["as_of"] = "2026-01-05T10:00:00"
        return labeled

    monkeypatch.setattr("app.forecasting.walkforward.label_dataset", naive)
    result = run_walk_forward(
        dataset,
        config=WalkForwardConfig(
            initial_train_size=6,
            validation_size=3,
            test_size=3,
            step_size=3,
            min_train=4,
            min_validation=2,
            min_test=3,
        ),
    )
    assert result["ok"] is False
    assert result["code"] == "INVALID_TIMESTAMP"
    assert result["artifact"] is None
    assert result["forecast_ready"] is False


def test_walk_forward_api_validation_and_authorization(client: TestClient):
    denied = client.post("/api/walk-forward", json={"instrument": "NIFTY"})
    assert denied.status_code == 401
    token = client.post("/api/session/login", json={"password": "test-password"}).json()
    assert client.post("/api/walk-forward", json={"instrument": "NIFTY"}).status_code == 403
    csrf = client.cookies.get("imm_csrf")
    headers = {"x-csrf-token": csrf}
    extra = client.post("/api/walk-forward", headers=headers, json={"instrument": "NIFTY", "path": "/tmp/x.json"})
    assert extra.status_code == 422
    url = client.post(
        "/api/walk-forward",
        headers=headers,
        json={"instrument": "NIFTY", "provider": "http://127.0.0.1/history"},
    )
    assert url.status_code == 400
    assert url.json()["code"] == "INVALID_PROVIDER"
    groww = client.post("/api/walk-forward", headers=headers, json={"instrument": "NIFTY", "provider": "groww"})
    assert groww.status_code == 501
    assert groww.json()["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert groww.json()["forecast_ready"] is False
    synthetic = client.post("/api/walk-forward", headers=headers, json={"instrument": "NIFTY", "provider": "synthetic"})
    assert synthetic.status_code == 422
    body = synthetic.json()
    assert body["code"] == "INSUFFICIENT_DATA"
    assert body["forecast_ready"] is False
    assert body["paper_approved"] is False
    assert body["live_approved"] is False
    assert body["real_market_data_verified"] is False
    assert body["artifact"] is None
    overlap = client.post(
        "/api/walk-forward",
        headers=headers,
        json={"instrument": "NIFTY", "provider": "synthetic", "step_size": 1, "test_size": 4},
    )
    assert overlap.status_code == 422
    assert overlap.json()["code"] == "OVERLAPPING_TEST"
    missing = client.get("/api/walk-forward/" + "ab" * 32)
    client.cookies.clear()
    unauthenticated = client.get("/api/walk-forward/" + "ab" * 32)
    assert unauthenticated.status_code == 401
    client.post("/api/session/login", json={"password": "test-password"})
    still_missing = client.get("/api/walk-forward/" + "ab" * 32)
    assert still_missing.status_code == 404
    assert missing.status_code == 404
    assert token is not None
