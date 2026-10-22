"""Quarantine provenance cannot be overridden on the training path."""

from __future__ import annotations

from app.features.definitions import FEATURE_SET_VERSION

import json
from datetime import datetime, timedelta

from app.features.pipeline import build_dataset
from app.features.service import rebuild_from_artifact
from app.forecasting.experiment import run_experiment
from app.forecasting.models import fit_last_return_sign, fit_logistic, fit_majority
from app.forecasting.targets import label_dataset
from app.forecasting.walkforward import run_walk_forward
from app.market.fixtures import fixture_calendar
from app.market.history import features_from_source
from app.market.provenance import evaluation_block, quarantine_training_block
from app.market.schemas import IST, Candle, DataOrigin, MarketSession
from app.settings import REPO_ROOT
from tests.test_forecasting import alternating, series
from tests.test_history import bars

REASON = "Quarantined Groww candles cannot be used as trusted training data."


def _assert_rejected(result: dict) -> None:
    assert result["ok"] is False
    assert result["code"] == "QUARANTINE_REJECTED"
    assert result.get("artifact") is None
    assert result.get("message") == REASON
    assert result.get("rows") in (None, [])
    assert "models" not in result
    assert "test_metrics" not in result


def test_forced_eligibility_does_not_admit_a_quarantine_record():
    payload = {
        "quarantine_id": "stored-response",
        "label": "UNVERIFIED_PROVIDER",
        "forecast_eligible": True,
        "origin": "SYNTHETIC",
        "candle_boundary_role": "end",
        "real_market_data_verified": False,
    }
    for result in (
        features_from_source(payload),
        label_dataset(payload),
        run_experiment(payload),
        run_walk_forward(payload),
    ):
        _assert_rejected(result)


def test_quarantine_id_without_a_status_is_rejected():
    payload = {"quarantine_id": "stored-response", "forecast_eligible": True, "origin": "DOCUMENTED_SAMPLE"}
    assert quarantine_training_block(payload) == ("QUARANTINE_REJECTED", REASON)
    _assert_rejected(label_dataset(payload))
    _assert_rejected(run_walk_forward(payload))


def test_unverified_provider_without_a_quarantine_id_is_rejected():
    payload = {"label": "UNVERIFIED_PROVIDER", "forecast_eligible": True, "origin": "SYNTHETIC"}
    _assert_rejected(features_from_source(payload))
    category = {"data_category": "UNVERIFIED_PROVIDER", "forecast_eligible": True, "origin": "SYNTHETIC"}
    _assert_rejected(run_experiment(category))


def test_mixed_dataset_is_rejected_as_a_whole():
    dataset = series(alternating())
    dataset["rows"].append({"quarantine_id": "stored-response", "direction": 1})
    labeled = label_dataset(dataset)
    trained = run_experiment(dataset)
    evaluated = run_walk_forward(dataset)
    for result in (labeled, trained, evaluated):
        _assert_rejected(result)


def test_missing_malformed_and_conflicting_provenance():
    missing = evaluation_block({}, require_verified_history=False)
    assert missing == (
        "MIXED_PROVENANCE",
        "The dataset origin is missing or is not a known provenance category.",
    )
    stripped = {
        "quarantine_id": "",
        "forecast_eligible": True,
        "origin": "SYNTHETIC",
        "timestamp_timezone": "UNVERIFIED",
        "candle_boundary": "UNVERIFIED",
    }
    _assert_rejected(features_from_source(stripped))
    conflicting = {
        "origin": "SYNTHETIC",
        "data_category": "UNVERIFIED_PROVIDER",
        "forecast_eligible": True,
        "candle_boundary_role": "end",
    }
    _assert_rejected(run_walk_forward(conflicting))
    _assert_rejected(label_dataset(conflicting))


def test_direct_feature_generation_rejects_a_quarantine_record():
    record = {
        "quarantine_id": "stored-response",
        "label": "UNVERIFIED_PROVIDER",
        "forecast_eligible": True,
        "feature_set_version": FEATURE_SET_VERSION,
        "source_candles": [],
    }
    built = build_dataset(record, fixture_calendar())
    assert built.ok is False
    assert built.code == "QUARANTINE_REJECTED"
    assert built.artifact is None
    rebuilt = rebuild_from_artifact(record)
    assert rebuilt.ok is False
    assert rebuilt.code == "QUARANTINE_REJECTED"
    assert rebuilt.artifact is None


def test_direct_label_training_and_walk_forward_reject_quarantine_records():
    record = {"label": "UNVERIFIED_PROVIDER", "forecast_eligible": True, "origin": "PROVIDER"}
    _assert_rejected(label_dataset(record))
    _assert_rejected(run_experiment(record))
    _assert_rejected(run_walk_forward(record))
    row = {"quarantine_id": "stored-response", "direction": 1, "ret_1": 0.1}
    for fitted in (fit_majority([row]), fit_last_return_sign([row]), fit_logistic([row, {"direction": 0}])):
        assert fitted["ok"] is False
        assert fitted["code"] == "QUARANTINE_REJECTED"
        assert "positive_probability" not in fitted


def _stored_ohlc_groups() -> list[list[tuple[float, float, float, float]]]:
    root = REPO_ROOT / "var" / "history" / "quarantine"
    groups = []
    for path in sorted(root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for row in record.get("raw_candles") or []:
            if isinstance(row, list) and len(row) >= 5:
                rows.append((float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        if rows:
            groups.append(rows)
    assert len(groups) >= 2
    return groups


def _fresh_candle(ohlc: tuple[float, float, float, float], step: int) -> Candle:
    start = datetime(2026, 1, 5, 9, 15, tzinfo=IST) + timedelta(minutes=15 * step)
    open_, high, low, close = ohlc
    return Candle(
        instrument_id="NIFTY",
        underlying="NIFTY",
        exchange=None,
        interval="M15",
        bar_start=start,
        bar_end=start + timedelta(minutes=15),
        provider_timestamp=None,
        retrieved_at=datetime(2026, 1, 5, 15, 30, tzinfo=IST),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=None,
        source_id="copied-without-provenance",
        origin=DataOrigin.SYNTHETIC,
        session=MarketSession.OPEN,
    )


def _assert_feature_rejected(result) -> None:
    assert result.ok is False
    assert result.code == "QUARANTINE_REJECTED"
    assert result.artifact is None


def test_copied_ohlc_keeps_quarantine_identity_without_markers():
    groups = _stored_ohlc_groups()
    for group in groups:
        copied = [_fresh_candle(ohlc, step) for step, ohlc in enumerate(group[:4])]
        _assert_feature_rejected(build_dataset(copied, fixture_calendar()))
    stripped = {
        "origin": "SYNTHETIC",
        "forecast_eligible": True,
        "candle_boundary_role": "end",
        "raw_candles": [["2026-01-05T09:15:00", *groups[0][0], None, None]],
    }
    for result in (
        features_from_source(stripped),
        label_dataset(stripped),
        run_experiment(stripped),
        run_walk_forward(stripped),
    ):
        _assert_rejected(result)


def test_mixed_and_rebuilt_copies_do_not_reach_training():
    quarantined = _stored_ohlc_groups()[0][0]
    mixed = bars(25)
    mixed[0] = mixed[0].model_copy(
        update={"open": quarantined[0], "high": quarantined[1], "low": quarantined[2], "close": quarantined[3]}
    )
    _assert_feature_rejected(build_dataset(mixed, fixture_calendar()))
    artifact = series(alternating())
    artifact["source_candles"][0]["open"] = quarantined[0]
    artifact["source_candles"][0]["high"] = quarantined[1]
    artifact["source_candles"][0]["low"] = quarantined[2]
    artifact["source_candles"][0]["close"] = quarantined[3]
    _assert_feature_rejected(rebuild_from_artifact(artifact))
    for result in (label_dataset(artifact), run_experiment(artifact), run_walk_forward(artifact)):
        _assert_rejected(result)
    priced = {"direction": 1, "open": quarantined[0], "high": quarantined[1], "low": quarantined[2], "close": quarantined[3]}
    for fitted in (fit_majority([priced, {"direction": 0}]), fit_last_return_sign([priced]), fit_logistic([priced, {"direction": 0}])):
        assert fitted["ok"] is False
        assert fitted["code"] == "QUARANTINE_REJECTED"
        assert "positive_probability" not in fitted


def test_verified_synthetic_dataset_still_builds_and_labels():
    built = build_dataset(bars(25), fixture_calendar())
    assert built.ok is True
    assert built.artifact is not None
    labeled = label_dataset(built.artifact)
    assert labeled["ok"] is True
    assert labeled["rows"]
    assert evaluation_block(built.artifact, require_verified_history=False) is None
    clean = fit_majority([{"direction": 0}, {"direction": 1}])
    assert clean["ok"] is True
    assert clean.get("code") != "QUARANTINE_REJECTED"
    shifted = [
        candle.model_copy(
            update={
                "open": candle.open + 12000,
                "high": candle.high + 12000,
                "low": candle.low + 12000,
                "close": candle.close + 12000,
            }
        )
        for candle in bars(25)
    ]
    nearby = build_dataset(shifted, fixture_calendar())
    assert nearby.ok is True
    assert nearby.artifact is not None
    assert nearby.artifact["forecast_ready"] is False
    assert nearby.artifact.get("real_market_data_verified") is not True
