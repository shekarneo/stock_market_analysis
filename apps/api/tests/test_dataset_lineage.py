"""Sealed lineage, not a caller flag or a price comparison, is the training boundary."""

from __future__ import annotations

import json

from app.features.pipeline import build_dataset
from app.features.service import rebuild_from_artifact
from app.forecasting.experiment import run_experiment
from app.forecasting.splits import SplitConfig
from app.forecasting.targets import label_dataset
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward
from app.market.fixtures import fixture_calendar
from app.market.history import HistoryStore, features_from_source, store_source_candles
from app.settings import REPO_ROOT
from tests.test_forecasting import alternating, series
from tests.test_history import bars

SMALL = SplitConfig(min_train=6, min_validation=2, min_test=3)
WINDOWS = WalkForwardConfig(
    initial_train_size=6,
    validation_size=3,
    test_size=3,
    step_size=3,
    min_train=4,
    min_validation=2,
    min_test=3,
)


def test_transformed_sealed_ohlc_cannot_be_labeled_rebuilt_or_trained():
    dataset = series(alternating())
    original_close = dataset["source_candles"][0]["close"]
    dataset["source_candles"][0]["close"] = original_close + 0.5
    labeled = label_dataset(dataset)
    trained = run_experiment(dataset, config=SMALL)
    evaluated = run_walk_forward(dataset, config=WINDOWS)
    rebuilt = rebuild_from_artifact(dataset)
    for result in (labeled, trained, evaluated):
        assert result["ok"] is False
        assert result["code"] == "LINEAGE_MISMATCH"
        assert result.get("artifact") is None
        assert result.get("rows") in (None, [])
        assert "models" not in result
        assert "test_metrics" not in result
    assert rebuilt.ok is False
    assert rebuilt.code == "LINEAGE_MISMATCH"
    assert rebuilt.artifact is None


def test_feature_rows_without_lineage_do_not_train():
    dataset = series(alternating())
    detached = {
        "origin": "SYNTHETIC",
        "feature_set_version": dataset["feature_set_version"],
        "interval": "M15",
        "forecast_ready": False,
        "rows": dataset["rows"],
        "source_candles": dataset["source_candles"],
    }
    trained = run_experiment(detached, config=SMALL)
    evaluated = run_walk_forward(detached, config=WINDOWS)
    for result in (trained, evaluated):
        assert result["ok"] is False
        assert result["code"] == "LINEAGE_MISSING"
        assert result["artifact"] is None
        assert "models" not in result
        assert "test_metrics" not in result


def test_quarantine_parent_and_unsealed_flag_are_rejected(tmp_path):
    parent = sorted((REPO_ROOT / "var" / "history" / "quarantine").glob("*.json"))[0].stem
    cited = build_dataset(bars(25), fixture_calendar(), history_dataset_id=parent, history_checksum=parent)
    assert cited.ok is True
    blocked = run_walk_forward(cited.artifact, config=WINDOWS)
    assert blocked["ok"] is False
    assert blocked["code"] == "QUARANTINE_REJECTED"
    assert blocked["artifact"] is None
    record = json.loads((REPO_ROOT / "var" / "history" / "quarantine" / f"{parent}.json").read_text(encoding="utf-8"))
    record.pop("label", None)
    record.pop("quarantine_id", None)
    record.pop("data_category", None)
    record.pop("timestamp_timezone", None)
    record.pop("candle_boundary", None)
    for row in record.get("raw_candles") or []:
        if isinstance(row, list) and len(row) >= 5:
            for index in range(1, 5):
                row[index] = float(row[index]) + 0.5
    record["origin"] = "SYNTHETIC"
    record["forecast_eligible"] = True
    for result in (
        features_from_source(record),
        run_experiment(record, config=SMALL),
        run_walk_forward(record, config=WINDOWS),
    ):
        assert result["ok"] is False
        assert result["code"] == "LINEAGE_MISSING"
        assert result.get("artifact") is None
    source = store_source_candles(bars(25), instrument="NIFTY", store=HistoryStore(tmp_path))
    forged = json.loads(json.dumps(source))
    forged["forecast_eligible"] = False
    assert features_from_source(forged)["code"] == "CHECKSUM_MISMATCH"
    built = features_from_source(source)
    assert built["ok"] is True
    assert built["artifact"]["lineage"]["market_data_verified"] is False
    assert built["artifact"]["lineage"]["research_declaration"] == "SYNTHETIC"
    assert built["artifact"]["forecast_ready"] is False


def test_explicit_synthetic_lineage_survives_research_use():
    dataset = series(alternating())
    assert dataset["lineage"]["research_declaration"] == "SYNTHETIC"
    assert dataset["lineage"]["market_data_verified"] is False
    labeled = label_dataset(dataset)
    assert labeled["ok"] is True
    assert labeled["lineage"]["origin"] == "SYNTHETIC"
    assert labeled["real_market_data_verified"] is False
    rebuilt = rebuild_from_artifact(dataset)
    assert rebuilt.ok is True
    assert rebuilt.artifact["lineage"]["origin"] == "SYNTHETIC"
    assert rebuilt.artifact["lineage"]["parent_dataset_id"] == dataset["dataset_id"]
    assert rebuilt.artifact["forecast_ready"] is False
    trained = run_experiment(dataset, config=SMALL)
    assert trained["ok"] is True
    assert trained["artifact"]["lineage"]["research_declaration"] == "SYNTHETIC"
    assert trained["artifact"]["forecast_ready"] is False
    assert trained["artifact"].get("real_market_data_verified") is not True
    evaluated = run_walk_forward(dataset, config=WINDOWS)
    assert evaluated["ok"] is True
    assert evaluated["artifact"]["lineage"]["origin"] == "SYNTHETIC"
    assert evaluated["artifact"]["forecast_ready"] is False
    assert evaluated["artifact"]["paper_approved"] is False
    assert evaluated["artifact"]["live_approved"] is False
    assert evaluated["artifact"]["real_market_data_verified"] is False
