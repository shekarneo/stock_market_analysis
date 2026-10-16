"""Read-only quarantine diagnostics. These tests do not call a provider."""

import json
from datetime import datetime

from app.features.pipeline import content_hash
from app.market.history import HistoryStore
from app.forecasting.targets import label_dataset
from app.forecasting.walkforward import run_walk_forward
from app.market.history import features_from_source
from app.market.quarantine_validation import ingestion_diagnostic, validate_quarantine_payload
from app.market.verified_history import build_trusted_dataset
from app.settings import REPO_ROOT


def _seal(body: dict) -> dict:
    digest = content_hash(body)
    sealed = dict(body)
    sealed["quarantine_id"] = digest
    sealed["checksum"] = digest
    return sealed


def _body(candles, **overrides) -> dict:
    body = {
        "label": "UNVERIFIED_PROVIDER",
        "candle_count": len(candles) if candles is not None else 1,
        "requested_start_sent": "2026-10-13 09:15:00",
        "requested_end_sent": "2026-10-13 15:30:00",
        "first_raw_timestamp": None if not candles else candles[0][0],
        "last_raw_timestamp": None if not candles else candles[-1][0],
        "raw_body_sha256": "b" * 64,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }
    if candles is not None:
        body["raw_candles"] = candles
    body.update(overrides)
    return body


def _ids(report: dict, status: str) -> set[str]:
    return {item["id"] for item in report[status]}


def test_valid_checksum_passes_and_invalid_checksum_fails():
    candles = [["2026-10-13T09:15:00", 10, 11, 9, 10, None]]
    valid = _seal(_body(candles, requested_end_sent="2026-10-13 09:15:00", candle_count=1))
    assert "checksum" in _ids(validate_quarantine_payload(valid), "passed")
    broken = dict(valid)
    broken["checksum"] = "0" * 64
    failed = validate_quarantine_payload(broken)
    assert "checksum" in _ids(failed, "failed")
    assert failed["trusted_dataset_created"] is False


def test_naive_and_aware_timestamps_do_not_establish_a_timezone():
    naive = _seal(_body([["2026-10-13T09:15:00", 10, 11, 9, 10, None]], requested_end_sent="2026-10-13 09:15:00", candle_count=1))
    aware = _seal(_body([["2026-10-13T09:15:00+05:30", 10, 11, 9, 10, None]], requested_end_sent="2026-10-13 09:15:00", candle_count=1))
    naive_report = validate_quarantine_payload(naive)
    aware_report = validate_quarantine_payload(aware)
    assert next(item["detail"] for item in naive_report["passed"] if item["id"] == "timezone_offset").startswith("Every stored timestamp is offset-less")
    assert "includes an offset" in next(item["detail"] for item in aware_report["passed"] if item["id"] == "timezone_offset")
    assert "timezone_identity" in _ids(naive_report, "undetermined")
    assert "timezone_identity" in _ids(aware_report, "undetermined")


def test_duplicate_unordered_and_incorrect_spacing_fail():
    duplicate = _seal(_body([
        ["2026-10-13T09:15:00", 10, 11, 9, 10, None],
        ["2026-10-13T09:15:00", 10, 11, 9, 10, None],
    ], candle_count=2))
    unordered = _seal(_body([
        ["2026-10-13T09:30:00", 10, 11, 9, 10, None],
        ["2026-10-13T09:15:00", 10, 11, 9, 10, None],
    ], candle_count=2))
    spaced = _seal(_body([
        ["2026-10-13T09:15:00", 10, 11, 9, 10, None],
        ["2026-10-13T09:20:00", 10, 11, 9, 10, None],
    ], candle_count=2))
    assert "duplicate_timestamps" in _ids(validate_quarantine_payload(duplicate), "failed")
    assert "timestamp_order" in _ids(validate_quarantine_payload(unordered), "failed")
    assert "spacing_15_minutes" in _ids(validate_quarantine_payload(spaced), "failed")


def test_invalid_ohlc_fails_without_becoming_trusted():
    invalid = _seal(_body([["2026-10-13T09:15:00", 10, 9, 8, 10, None]], requested_end_sent="2026-10-13 09:15:00", candle_count=1))
    report = validate_quarantine_payload(invalid)
    assert "ohlc" in _ids(report, "failed")
    assert report["trusted_dataset_created"] is False
    assert build_trusted_dataset()["dataset_id"] is None


def test_missing_requested_endpoint_fails_and_session_boundary_stays_undetermined():
    missing_open = _seal(_body([
        ["2026-10-13T09:30:00", 10, 11, 9, 10, None],
        ["2026-10-13T15:30:00", 10, 11, 9, 10, None],
    ], candle_count=2))
    report = validate_quarantine_payload(missing_open)
    assert "requested_endpoints" in _ids(report, "failed")
    assert "session_boundaries" in _ids(report, "undetermined")
    assert "request_boundary_semantics" in _ids(report, "undetermined")
    assert "expected_observation_count" in _ids(report, "undetermined")


def test_summary_without_candles_differs_from_the_raw_record_and_is_not_repaired(tmp_path):
    candles = [["2026-10-13T09:15:00", 10, 11, 9, 10, None]]
    complete = _seal(_body(candles, requested_end_sent="2026-10-13 09:15:00", candle_count=1))
    summary = _seal(_body(None, requested_end_sent="2026-10-13 09:15:00", candle_count=1, first_raw_timestamp=candles[0][0], last_raw_timestamp=candles[0][0], raw_body_sha256=complete["raw_body_sha256"]))
    before = json.dumps(complete, sort_keys=True)
    report = validate_quarantine_payload(complete, [summary])
    assert json.dumps(complete, sort_keys=True) == before
    assert "raw_summary_match" in _ids(report, "failed")
    assert "ohlc" in _ids(validate_quarantine_payload(summary, [complete]), "undetermined")
    path = tmp_path / "record.json"
    path.write_text(before, encoding="utf-8")
    validate_quarantine_payload(json.loads(path.read_text(encoding="utf-8")))
    assert path.read_text(encoding="utf-8") == before


def test_stored_quarantine_is_diagnosed_without_mutation_or_a_trusted_dataset():
    root = REPO_ROOT / "var" / "history" / "quarantine"
    complete_path = root / "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057.json"
    summary_path = root / "5edd4d3543825aa3a385092b9d16b3938e5995e026cbf3b2ade0872c18414a5d.json"
    before = {path: path.read_bytes() for path in (complete_path, summary_path)}
    complete = json.loads(before[complete_path])
    summary = json.loads(before[summary_path])
    complete_report = validate_quarantine_payload(complete, [summary])
    summary_report = validate_quarantine_payload(summary, [complete])
    assert {path: path.read_bytes() for path in before} == before
    assert _ids(complete_report, "passed") >= {
        "checksum",
        "stored_candle_count",
        "timestamp_parse",
        "timestamp_order",
        "duplicate_timestamps",
        "spacing_15_minutes",
        "timezone_offset",
        "requested_endpoints",
        "ohlc",
        "volume",
        "open_interest",
    }
    assert _ids(complete_report, "failed") == {"raw_summary_match"}
    assert _ids(complete_report, "undetermined") >= {
        "raw_http_body",
        "timezone_identity",
        "expected_observation_count",
        "session_boundaries",
        "request_boundary_semantics",
    }
    assert "ohlc" in _ids(summary_report, "undetermined")
    assert "raw_summary_match" in _ids(summary_report, "failed")
    for report in (complete_report, summary_report):
        assert report["trusted_dataset_created"] is False
        assert report["forecast_ready"] is False
        assert report["paper_approved"] is False
        assert report["live_approved"] is False
        assert report["real_market_data_verified"] is False
    assert build_trusted_dataset()["trusted_dataset_created"] is False


def test_one_minute_gaps_stay_unclassified_and_untrusted():
    candles = [
        ["2026-10-13T09:15:00", 100, 101, 99, 100.5, None, None],
        ["2026-10-13T09:16:00", 100.5, 102, 100, 101, None, None],
        ["2026-10-13T09:17:00", 101, 101.5, 100.5, 101.2, None, None],
        ["2026-10-13T09:20:00", 101.2, 103, 101, 102, None, None],
    ]
    record = _seal(
        _body(
            candles,
            candle_interval="1minute",
            requested_end_sent="2026-10-13 09:20:00",
            candle_count=4,
        )
    )
    report = validate_quarantine_payload(record)
    assert "spacing_1_minute" in _ids(report, "undetermined")
    assert "spacing_15_minutes" not in _ids(report, "failed")
    assert "timezone_identity" in _ids(report, "undetermined")
    assert "session_boundaries" in _ids(report, "undetermined")
    assert report["trusted_dataset_created"] is False
    assert report["real_market_data_verified"] is False
    regular = [
        ["2026-10-13T09:15:00", 100, 101, 99, 100, None, None],
        ["2026-10-13T09:16:00", 100, 101, 99, 100, None, None],
    ]
    regular_record = _seal(
        _body(regular, candle_interval="1minute", requested_end_sent="2026-10-13 09:16:00", candle_count=2)
    )
    regular_report = validate_quarantine_payload(regular_record)
    assert "spacing_1_minute" in _ids(regular_report, "passed")
    assert regular_report["forecast_ready"] is False
    assert regular_report["paper_approved"] is False
    assert regular_report["live_approved"] is False
    assert HistoryStore(REPO_ROOT / "var" / "history").list_ids() == []
    assert datetime.fromisoformat("2026-10-13T09:15:00").tzinfo is None


def test_ingestion_diagnostic_keeps_structure_separate_from_the_contract():
    candles = [
        ["2026-10-13T09:15:00", 100, 101, 99, 100, None, None],
        ["2026-10-13T09:16:00", 100, 102, 99, 101, None, None],
    ]
    record = _seal(
        _body(
            candles,
            provider="groww",
            candle_interval="1minute",
            requested_end_sent="2026-10-13 09:16:00",
            candle_count=2,
            http_status=200,
            provider_status="SUCCESS",
            groww_symbol="NSE-NIFTY",
        )
    )
    before = json.dumps(record, sort_keys=True)
    diagnostic = ingestion_diagnostic(record)
    assert json.dumps(record, sort_keys=True) == before
    assert diagnostic["endpoint"] == "GET /v1/historical/candles"
    assert diagnostic["instrument"] == "NSE-NIFTY"
    assert diagnostic["interval"] == "1minute"
    assert diagnostic["http_status"] == 200
    assert diagnostic["provider_status"] == "SUCCESS"
    assert diagnostic["candle_count"] == 2
    assert diagnostic["observed_spacing_seconds"] == 60.0
    assert diagnostic["timestamp_format_observed"] == "offset-less ISO-8601 text"
    assert diagnostic["structural_validation"] == "PASS"
    assert diagnostic["provider_contract_verified"] is False
    assert diagnostic["timestamp_semantics_verified"] is False
    assert diagnostic["session_semantics_verified"] is False
    assert diagnostic["label"] == "UNVERIFIED_PROVIDER"
    assert diagnostic["trusted_dataset_created"] is False
    assert diagnostic["real_market_data_verified"] is False


def test_quarantine_payload_cannot_enter_features_labels_or_training():
    payload = {
        "quarantine_id": "stored-response",
        "label": "UNVERIFIED_PROVIDER",
        "data_category": "UNVERIFIED_PROVIDER",
        "origin": "SYNTHETIC",
        "forecast_eligible": True,
        "forecast_ready": False,
        "candle_boundary_role": "end",
        "real_market_data_verified": False,
        "paper_approved": False,
        "live_approved": False,
        "raw_candles": [["2026-10-13T09:15:00", 1, 2, 1, 1, None, None]],
    }
    features = features_from_source(payload)
    labels = label_dataset(payload)
    trained = run_walk_forward(payload)
    for result in (features, labels, trained):
        assert result["ok"] is False
        assert result["code"] == "QUARANTINE_REJECTED"
        assert result.get("artifact") is None
    assert payload["real_market_data_verified"] is False
    assert payload["forecast_ready"] is False
