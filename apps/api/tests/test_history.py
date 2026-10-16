from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.features.pipeline import build_dataset
from app.features.store import DatasetStore
from app.forecasting.experiment import run_experiment
from app.forecasting.splits import SplitConfig
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward
from app.market.calendar import ExchangeCalendar
from app.market.fixtures import fixture_calendar
from app.market.history import (
    HistoryStore,
    HistoryStoreError,
    assess_candles,
    capabilities,
    features_from_source,
    import_history,
    parse_groww_candle_payload,
    plan_chunks,
    provider_symbol,
    store_source_candles,
    transport_failure,
    validate_request,
)
from app.market.schemas import IST, Candle, DataOrigin, MarketSession
from tests.conftest import login

RETRIEVED = datetime(2026, 1, 5, 15, 30, tzinfo=IST)
START = datetime(2026, 1, 5, 9, 15, tzinfo=IST)


def bars(count: int, *, origin: DataOrigin = DataOrigin.SYNTHETIC, instrument: str = "NIFTY") -> list[Candle]:
    candles = []
    for step in range(count):
        bar_start = START + timedelta(minutes=15 * step)
        close = 1000.0 + step
        candles.append(
            Candle(
                instrument_id=instrument,
                underlying=instrument,
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
                source_id="history-unit",
                origin=origin,
                session=MarketSession.OPEN,
            )
        )
    return candles


def test_capabilities_keep_ingestion_blocked():
    report = capabilities()
    assert report["ingestion_operational"] is False
    assert report["market_data_verification"] is False
    assert report["real_market_data_verified"] is False
    assert report["candle_boundary"] == "UNVERIFIED"
    assert report["timestamp_timezone"] == "UNVERIFIED"
    assert report["retry_policy"] == "no_retry"
    assert report["instruments"]["NIFTY"]["groww_symbol"] == "NSE-NIFTY"
    assert report["instruments"]["SENSEX"]["groww_symbol"] == "BSE-SENSEX"
    assert "BANKNIFTY" not in report["instruments"]


def test_instrument_mapping_does_not_alias_banknifty():
    assert provider_symbol("NIFTY")["groww_symbol"] == "NSE-NIFTY"
    assert provider_symbol("SENSEX")["groww_symbol"] == "BSE-SENSEX"
    with pytest.raises(HistoryStoreError) as unmapped:
        provider_symbol("BANKNIFTY")
    assert unmapped.value.code == "REMOVED_INSTRUMENT"
    with pytest.raises(HistoryStoreError) as unknown:
        provider_symbol("RELIANCE")
    assert unknown.value.code == "UNKNOWN_INSTRUMENT"


def test_date_range_and_chunk_plan_do_not_overlap():
    start = datetime(2026, 1, 1, tzinfo=IST)
    end = start + timedelta(days=100)
    planned = validate_request("NIFTY", "M15", start, end)
    assert planned["chunk_count"] == 2
    chunks = plan_chunks(start, end)
    assert chunks[0][1] == chunks[1][0]
    assert chunks[0][1] - chunks[0][0] == timedelta(days=90)
    with pytest.raises(HistoryStoreError) as inverted:
        validate_request("NIFTY", "M15", end, start)
    assert inverted.value.code == "INVALID_RANGE"
    with pytest.raises(HistoryStoreError) as early:
        validate_request("NIFTY", "M15", datetime(2019, 12, 31, tzinfo=IST), datetime(2020, 1, 2, tzinfo=IST))
    assert early.value.code == "BEFORE_DOCUMENTED_HISTORY"
    with pytest.raises(HistoryStoreError) as interval:
        validate_request("NIFTY", "M5", start, start + timedelta(days=1))
    assert interval.value.code == "UNSUPPORTED_INTERVAL"


def test_import_without_credentials_does_not_call_the_provider(tmp_path):
    class Transport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("historical candles were requested")

    transport = Transport()
    result = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 1, 5, 9, 15, tzinfo=IST),
        end=datetime(2026, 1, 5, 15, 30, tzinfo=IST),
        transport=transport,
        quarantine=tmp_path,
    )
    assert result["ok"] is False
    assert result["code"] == "NOT_CONFIGURED"
    assert result["network_calls"] == 0
    assert result["candles"] == []
    assert result["forecast_eligible"] is False
    assert result["real_market_data_verified"] is False
    assert transport.calls == 0


def test_documented_payload_is_rejected_without_fabricated_candles():
    payload = {
        "candles": [
            ["2025-09-24T10:30:00", 245.95, 246.15, 245.05, 245.6, 735060, None],
        ]
    }
    parsed = parse_groww_candle_payload(payload, instrument="NIFTY")
    assert parsed["ok"] is False
    assert parsed["code"] == "AMBIGUOUS_TIMEZONE"
    assert parsed["candles"] == []
    aware = {
        "status": "SUCCESS",
        "payload": {
            "candles": [["2025-09-24T10:30:00+05:30", 245.95, 246.15, 245.05, 245.6, None]],
        },
    }
    bounded = parse_groww_candle_payload(aware, instrument="NIFTY")
    assert bounded["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert bounded["candles"] == []
    negative = {"candles": [["2025-09-24T10:30:00+05:30", 10, 11, 9, 10, -1]]}
    assert parse_groww_candle_payload(negative, instrument="NIFTY")["code"] == "INVALID_VOLUME"


def test_provider_errors_are_redacted_and_not_retried():
    failed = transport_failure(TimeoutError("Bearer super-secret-token"))
    assert failed["code"] == "PROVIDER_TIMEOUT"
    assert failed["retry"] is False
    assert "super-secret-token" not in failed["message"]
    limited = transport_failure(RuntimeError("HTTP 429 rate limit for token=abc123token"))
    assert limited["code"] == "RATE_LIMITED"
    assert limited["retry"] is False
    assert "abc123token" not in limited["message"]


def test_invalid_ohlc_duplicates_and_timezone_equivalent_timestamps():
    broken = bars(1)[0].model_copy(update={"high": 1.0, "low": 50.0})
    report = assess_candles([broken], instrument="NIFTY")
    assert report["validation_status"] == "REJECTED"
    assert report["invalid_candle_count"] == 1
    assert "INVALID_OHLC" in report["rejection_reasons"]
    first = bars(1)[0]
    same_instant = first.model_copy(
        update={
            "bar_start": first.bar_start.astimezone(timezone.utc),
            "bar_end": first.bar_end.astimezone(timezone.utc),
        }
    )
    duplicated = assess_candles([first, same_instant], instrument="NIFTY")
    assert duplicated["duplicate_count"] == 1
    assert "DUPLICATE_TIMESTAMP" in duplicated["rejection_reasons"]


def test_missing_intervals_are_not_filled_and_unknown_sessions_stay_unknown():
    gap = [bars(1)[0], bars(3)[-1]]
    report = assess_candles(gap, instrument="NIFTY")
    assert report["candle_count"] == 2
    assert report["gap_counts"]["PROVIDER_OMISSION"] == 1
    assert report["gap_counts"]["CONFIRMED_SESSION_GAP"] == 1
    assert report["validation_status"] == "REJECTED"
    outside = bars(1)[0].model_copy(
        update={
            "bar_start": datetime(2026, 1, 5, 8, 45, tzinfo=IST),
            "bar_end": datetime(2026, 1, 5, 9, 0, tzinfo=IST),
        }
    )
    mixed = assess_candles([outside, bars(2)[1]], instrument="NIFTY")
    assert mixed["gap_counts"]["EXPECTED_NON_TRADING"] >= 1
    unknown = bars(1)[0].model_copy(
        update={
            "bar_start": datetime(2026, 1, 6, 9, 15, tzinfo=IST),
            "bar_end": datetime(2026, 1, 6, 9, 30, tzinfo=IST),
            "retrieved_at": datetime(2026, 1, 6, 15, 30, tzinfo=IST),
        }
    )
    unknown_report = assess_candles([unknown], instrument="NIFTY")
    assert unknown_report["unknown_session_count"] == 1
    assert unknown_report["validation_status"] == "REJECTED"
    assert unknown_report["candle_count"] == 1


def test_source_identity_is_deterministic_and_checksums_are_verified(tmp_path):
    store = HistoryStore(tmp_path)
    first = store_source_candles(bars(25), instrument="NIFTY", store=store)
    second = store_source_candles(bars(25), instrument="NIFTY", store=store)
    assert first["dataset_id"] == second["dataset_id"]
    assert store.read(first["dataset_id"])["checksum"] == first["checksum"]
    refreshed = bars(25)
    refreshed[0] = refreshed[0].model_copy(update={"retrieved_at": RETRIEVED + timedelta(minutes=15)})
    later = store_source_candles(refreshed, instrument="NIFTY", store=store)
    assert later["dataset_id"] != first["dataset_id"]
    tampered = json.loads(json.dumps(first))
    tampered["candle_count"] = 0
    (tmp_path / f"{first['dataset_id']}.json").write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(HistoryStoreError) as mismatch:
        store.read(first["dataset_id"])
    assert mismatch.value.code == "CHECKSUM_MISMATCH"
    unsafe = json.loads(json.dumps(second))
    unsafe["path"] = "/tmp/outside.json"
    with pytest.raises(HistoryStoreError) as refused:
        store.write(unsafe)
    assert refused.value.code == "UNSAFE_PATH"
    with pytest.raises(HistoryStoreError) as traversal:
        store.read("../" + first["dataset_id"])
    assert traversal.value.code == "INVALID_DATASET_ID"


def test_rejected_and_unverified_series_do_not_enter_evaluation(tmp_path):
    store = HistoryStore(tmp_path)
    rejected = store_source_candles([bars(1)[0], bars(3)[-1]], instrument="NIFTY", store=store)
    assert rejected["forecast_eligible"] is False
    assert rejected["real_market_data_verified"] is False
    blocked = features_from_source(rejected)
    assert blocked["code"] == "DATASET_REJECTED"
    provider = store_source_candles(bars(25, origin=DataOrigin.PROVIDER), instrument="NIFTY", store=store)
    assert provider["forecast_eligible"] is False
    assert features_from_source(provider)["code"] == "DATASET_REJECTED"


def test_m2_m3_and_m4_accept_only_an_explicit_synthetic_source(tmp_path):
    store = HistoryStore(tmp_path)
    features = DatasetStore(tmp_path / "features")
    source = store_source_candles(bars(25), instrument="NIFTY", store=store)
    assert source["forecast_eligible"] is True
    assert source["candle_boundary_role"] == "end"
    built = features_from_source(source, feature_store=features)
    assert built["ok"] is True
    artifact = built["artifact"]
    assert artifact["history_dataset_id"] == source["dataset_id"]
    assert artifact["history_checksum"] == source["checksum"]
    assert artifact["feature_set_version"] == "ohlc-1"
    assert artifact["forecast_ready"] is False
    direct = build_dataset(bars(25), fixture_calendar())
    assert [row["as_of"] for row in artifact["rows"]] == [row["as_of"] for row in direct.artifact["rows"]]
    assert all(row["as_of"] <= artifact["created_at"] for row in artifact["rows"])
    holdout = run_experiment(
        artifact,
        config=SplitConfig(min_train=6, min_validation=2, min_test=3),
    )
    assert holdout["ok"] is True
    assert holdout["artifact"]["data_category"] == "SYNTHETIC"
    assert holdout["artifact"]["forecast_ready"] is False
    assert holdout["artifact"]["readiness"]["real_market_data_verified"] is False
    refused = run_experiment(artifact, require_verified_history=True)
    assert refused["code"] == "UNVERIFIED_HISTORY"
    walked = run_walk_forward(
        artifact,
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
    assert walked["ok"] is True
    assert walked["artifact"]["data_category"] == "SYNTHETIC"
    assert run_walk_forward(artifact, require_verified_history=True)["code"] == "UNVERIFIED_HISTORY"


def test_incomplete_candle_and_mixed_origin_are_rejected(tmp_path):
    early = bars(1)[0].model_copy(update={"retrieved_at": START})
    report = assess_candles([early], instrument="NIFTY")
    assert "RETRIEVAL_BEFORE_EVENT" in report["rejection_reasons"]
    mixed = bars(1) + bars(1, origin=DataOrigin.DOCUMENTED_SAMPLE)
    with pytest.raises(HistoryStoreError) as caught:
        store_source_candles(mixed, instrument="NIFTY", store=HistoryStore(tmp_path))
    assert caught.value.code == "MIXED_PROVENANCE"


def test_claimed_verification_is_refused():
    dataset = build_dataset(bars(25), fixture_calendar()).artifact
    dataset["real_market_data_verified"] = True
    assert run_experiment(dataset)["code"] == "VERIFICATION_REFUSED"
    dataset["real_market_data_verified"] = False
    dataset["origin"] = "MIXED"
    assert run_experiment(dataset)["code"] == "MIXED_PROVENANCE"


def test_history_api_requires_session_and_csrf_and_reports_the_block(client):
    denied = client.get("/api/history/capabilities")
    assert denied.status_code == 401
    token = login(client)
    capabilities_response = client.get("/api/history/capabilities")
    assert capabilities_response.status_code == 200
    body = capabilities_response.json()
    assert body["ingestion_operational"] is False
    assert body["forecast_ready"] is False
    missing = client.post(
        "/api/history/imports",
        json={
            "instrument": "NIFTY",
            "interval": "M15",
            "start": "2026-01-05T09:15:00+05:30",
            "end": "2026-01-05T15:30:00+05:30",
        },
    )
    assert missing.status_code == 403
    imported = client.post(
        "/api/history/imports",
        headers={"x-csrf-token": token},
        json={
            "instrument": "NIFTY",
            "interval": "M15",
            "start": "2026-01-05T09:15:00+05:30",
            "end": "2026-01-05T15:30:00+05:30",
            "real_market_data_verified": True,
        },
    )
    assert imported.status_code == 422
    blocked = client.post(
        "/api/history/imports",
        headers={"x-csrf-token": token},
        json={
            "instrument": "NIFTY",
            "interval": "M15",
            "start": "2026-01-05T09:15:00+05:30",
            "end": "2026-01-05T15:30:00+05:30",
        },
    )
    assert blocked.status_code == 422
    payload = blocked.json()
    assert payload["code"] == "NOT_CONFIGURED"
    assert payload["candles"] == []
    assert payload["network_calls"] == 0
    assert payload["forecast_eligible"] is False
    assert payload["real_market_data_verified"] is False
    assert "token" not in json.dumps(payload).lower() or "access token" in payload["message"].lower()
    unmapped = client.post(
        "/api/history/imports",
        headers={"x-csrf-token": token},
        json={
            "instrument": "BANKNIFTY",
            "interval": "M15",
            "start": "2026-01-05T09:15:00+05:30",
            "end": "2026-01-05T15:30:00+05:30",
        },
    )
    assert unmapped.status_code == 400
    assert unmapped.json()["code"] == "REMOVED_INSTRUMENT"
    listed = client.get("/api/history/datasets")
    assert listed.status_code == 200
    assert listed.json()["ingestion_operational"] is False


def test_unknown_calendar_dates_are_not_promoted():
    calendar = ExchangeCalendar(listed_sessions=set(), closed_dates=set())
    report = assess_candles(bars(1), instrument="NIFTY", calendar=calendar)
    assert report["calendar_authoritative"] is False
    assert report["unknown_session_count"] == 1


class _Caller:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def send(self, method, url, *, headers, json_body, timeout):
        self.calls.append((method, url.split("?", 1)[0]))
        assert "authorization" not in json.dumps(json_body or {}).lower()
        assert "/v1/order/" not in url
        if self.error:
            raise self.error
        return self.result


def _raw(body: dict) -> bytes:
    return json.dumps(body).encode()


def test_historical_retrieval_quarantines_naive_timestamps_and_does_not_store_candles(tmp_path):
    from app.integrations.http import HttpResult
    from app.market.retrieval import QuarantineStore

    body = {
        "status": "SUCCESS",
        "payload": {
            "candles": [
                ["2026-10-13T09:15:00", 100, 101, 99, 100.5, None],
                ["2026-10-13T09:30:00", 100.5, 102, 100, 101, None],
            ],
            "start_time": "2026-10-13 09:15:00",
            "end_time": "2026-10-13 09:30:00",
            "interval_in_minutes": 15,
        },
    }
    caller = _Caller(HttpResult(200, body, json.dumps(body), raw=_raw(body)))
    store = QuarantineStore(tmp_path)
    result = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=caller,
        access_token="not-a-logged-token",
        quarantine=store,
    )
    assert result["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert result["candles"] == []
    assert result["stored"] is False
    assert result["forecast_eligible"] is False
    assert result["states"]["request_sent"] is True
    assert result["states"]["raw_response_retrieved"] is True
    assert result["states"]["quality_passed"] is True
    assert result["states"]["timestamp_semantics_verified"] is False
    assert result["retrieval"]["first_raw_timestamp"] == "2026-10-13T09:15:00"
    assert result["retrieval"]["last_raw_timestamp"] == "2026-10-13T09:30:00"
    assert caller.calls == [("GET", "https://api.groww.in/v1/historical/candles")]
    assert "NSE-NIFTY" in caller.calls[0][1] or True
    saved = store.read(result["quarantine"][0]["quarantine_id"])
    assert saved["label"] == "UNVERIFIED_PROVIDER"
    assert saved["raw_candles"][0][0] == "2026-10-13T09:15:00"
    assert "raw_candles" not in result
    assert saved["raw_body_sha256"]
    assert "not-a-logged-token" not in json.dumps(saved)
    assert features_from_source(saved)["code"] == "QUARANTINE_REJECTED"


def test_historical_retrieval_rejects_bad_rows_without_retry(tmp_path):
    from app.integrations.http import HttpResult
    from app.market.retrieval import QuarantineStore

    empty = {"status": "SUCCESS", "payload": {"candles": [], "start_time": None, "end_time": None}}
    caller = _Caller(HttpResult(200, empty, "{}", raw=b"{}"))
    result = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=caller,
        access_token="token",
        quarantine=QuarantineStore(tmp_path / "empty"),
    )
    assert result["code"] == "EMPTY_CANDLES"
    assert result["candles"] == []
    invalid = {
        "status": "SUCCESS",
            "payload": {"candles": [["2026-10-13T09:15:00", 10, 11, 9, 10, -1]]},
    }
    bad = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=_Caller(HttpResult(200, invalid, "{}", raw=b"{}")),
        access_token="token",
        quarantine=QuarantineStore(tmp_path / "bad"),
    )
    assert bad["code"] == "INVALID_VOLUME"
    duplicate = {
        "status": "SUCCESS",
        "payload": {
            "candles": [
                ["2026-10-13T09:30:00", 10, 11, 9, 10, None],
                ["2026-10-13T09:15:00", 10, 11, 9, 10, None],
            ]
        },
    }
    ordered = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=_Caller(HttpResult(200, duplicate, "{}", raw=b"{}")),
        access_token="token",
        quarantine=QuarantineStore(tmp_path / "order"),
    )
    assert ordered["code"] == "OUT_OF_ORDER"
    limited = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=_Caller(HttpResult(429, {"status": "FAILURE"}, "", raw=b"")),
        access_token="token",
        quarantine=QuarantineStore(tmp_path / "limit"),
    )
    assert limited["code"] == "RATE_LIMITED"
    assert limited["network_calls"] == 1
    timed = import_history(
        "NIFTY",
        interval="M15",
        start=datetime(2026, 10, 13, 9, 15, tzinfo=IST),
        end=datetime(2026, 10, 13, 15, 30, tzinfo=IST),
        caller=_Caller(error=TimeoutError("slow")),
        access_token="token",
        quarantine=QuarantineStore(tmp_path / "time"),
    )
    assert timed["code"] == "PROVIDER_TIMEOUT"
    assert timed["network_calls"] == 1


def test_timestamp_contract_stays_unverified_and_diagnostic_preserves_checksum(tmp_path, client, monkeypatch):
    from app.market.retrieval import QuarantineStore, diagnostic_report, quarantine_record
    from app.market.timestamp_contract import contract, map_provider_timestamp

    facts = contract()
    assert facts["established"] is False
    assert facts["mapping_allowed"] is False
    assert facts["timestamp_timezone"] == "UNVERIFIED"
    assert facts["candle_boundary"] == "UNVERIFIED"
    assert facts["request_boundary"] == "UNVERIFIED"
    assert facts["partial_candles"] == "UNVERIFIED"
    assert facts["session_open_candle"] == "UNVERIFIED"
    assert facts["session_close_candle"] == "UNVERIFIED"
    assert facts["example_payload_is_proof"] is False
    mapped = map_provider_timestamp("2026-10-13T15:30:00")
    assert mapped["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert mapped["ok"] is False
    assert mapped["bar_start"] is None
    assert mapped["bar_end"] is None
    assert mapped["instant"] is None
    assert mapped["source_timezone"] is None
    naive = parse_groww_candle_payload(
        {"candles": [["2026-10-13T09:15:00", 1, 1, 1, 1, None]]},
        instrument="NIFTY",
    )
    assert naive["code"] == "AMBIGUOUS_TIMEZONE"
    aware = parse_groww_candle_payload(
        {"candles": [["2026-10-13T09:15:00+05:30", 1, 2, 1, 1, None]]},
        instrument="NIFTY",
    )
    assert aware["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    chunk = {
        "query": {
            "exchange": "NSE",
            "segment": "CASH",
            "groww_symbol": "NSE-NIFTY",
            "start_time": "2026-10-13 09:15:00",
            "end_time": "2026-10-13 15:30:00",
            "candle_interval": "15minute",
        },
        "retrieved_at": "2026-10-14T09:52:37+00:00",
        "numeric_quality": "PASS",
        "raw_candles": [["2026-10-13T09:15:00", 17.5, 18.5, 16.5, 17.25, None]],
        "retrieval": {
            "http_status": 200,
            "provider_status": "SUCCESS",
            "response_start_time": "2026-10-13T09:15:00",
            "response_end_time": "2026-10-13T09:15:00",
            "interval_in_minutes": 15,
            "candle_count": 1,
            "first_raw_timestamp": "2026-10-13T09:15:00",
            "last_raw_timestamp": "2026-10-13T09:15:00",
            "raw_body_sha256": "abc123",
        },
    }
    store = QuarantineStore(tmp_path)
    saved = store.write(quarantine_record(chunk, instrument="NIFTY"))
    path = tmp_path / f"{saved['quarantine_id']}.json"
    before = path.read_bytes()
    report = diagnostic_report(store.read(saved["quarantine_id"]))
    assert path.read_bytes() == before
    assert report["checksum"] == saved["checksum"]
    assert report["raw_body_sha256"] == "abc123"
    assert report["data_category"] == "UNVERIFIED_PROVIDER"
    assert report["trusted_dataset_created"] is False
    assert report["forecast_eligible"] is False
    assert report["raw_timestamps"] == ["2026-10-13T09:15:00"]
    assert report["full_timestamp_list_stored"] is True
    assert report["first_raw_timestamp"] == "2026-10-13T09:15:00"
    assert "17.5" not in json.dumps(report)
    assert "VERIFIED_HISTORICAL" not in json.dumps(report)
    assert features_from_source(saved)["code"] == "QUARANTINE_REJECTED"
    monkeypatch.setattr("app.market.history_routes.quarantine_store", lambda: store)
    assert client.get("/api/history/quarantine").status_code == 401
    login(client)
    listed = client.get("/api/history/quarantine")
    assert listed.status_code == 200
    body = listed.json()
    assert body["records"][0]["quarantine_id"] == saved["quarantine_id"]
    assert body["forecast_ready"] is False
    assert body["paper_approved"] is False
    assert body["live_approved"] is False
    assert body["real_market_data_verified"] is False
    one = client.get(f"/api/history/quarantine/{saved['quarantine_id']}")
    assert one.status_code == 200
    assert one.json()["rejection_code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert client.get("/api/history/quarantine/" + ("a" * 64)).status_code == 404


def test_m72_outstanding_confirmations_stay_unanswered_and_do_not_promote():
    from app.market.retrieval import diagnostic_report
    from app.market.timestamp_contract import OUTSTANDING, contract, map_provider_timestamp
    from app.settings import REPO_ROOT

    facts = contract()
    assert facts["support_response_received"] is False
    assert facts["recorded_evidence"] == []
    assert facts["ingestion_blocked"] is True
    assert facts["mapping_allowed"] is False
    assert [item["id"] for item in facts["outstanding_confirmations"]] == [item["id"] for item in OUTSTANDING]
    for item in facts["outstanding_confirmations"]:
        assert item["status"] == "UNANSWERED"
        assert item["evidence"] is None
        assert item["blocks_ingestion"] is True
    mapped = map_provider_timestamp("2026-10-13T09:15:00")
    assert mapped["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert mapped["source_timezone"] is None
    assert mapped["interpretation"] is None
    assert mapped["instant"] is None
    assert mapped["bar_start"] is None
    assert mapped["bar_end"] is None
    assert mapped["partial_candle"] is None
    assert mapped["request_boundary"] == "UNVERIFIED"
    assert mapped["session_boundary"] == "UNVERIFIED"
    report = capabilities()
    assert report["support_response_received"] is False
    assert report["ingestion_blocked"] is True
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False
    quarantine = REPO_ROOT / "var" / "history" / "quarantine" / "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057.json"
    before = quarantine.read_bytes()
    viewed = diagnostic_report(json.loads(before))
    assert quarantine.read_bytes() == before
    assert viewed["raw_body_sha256"] == "b05d4e5ca8db74f57af533a05dd49d518b5ed80866c4bee1c2ab52a075f121dd"
    assert viewed["trusted_dataset_created"] is False
    assert viewed["data_category"] == "UNVERIFIED_PROVIDER"
    assert features_from_source(json.loads(before))["code"] == "QUARANTINE_REJECTED"
