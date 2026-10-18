"""Tests for Persistent Market Data Storage, Audit, and Benchmark Cache.

Verifies:
1. Durable database persistence of normalized Groww candles with unique (symbol, interval, timestamp) keys.
2. Immutable filesystem storage of raw API responses, with SHA-256 hashes and file paths in the database.
3. Unique constraint enforcement on (symbol, interval, timestamp).
4. Incremental and idempotent ingestion without duplicate creation.
5. Missing range detection (subsequent runs fetch only missing historical sub-ranges).
6. Never redownload the entire history unnecessarily (0 API calls when data is present).
7. Conflict detection and audit trail (logs conflicting OHLCV and resolves complete over partial).
8. Resumable ingestion runs surviving failures and restarts.
9. Dataset provenance and quality check persistence.
10. Benchmark result caching keyed by dataset version/hash, model version, features, target, and evaluation settings.
11. Invalidation of cached results when relevant inputs change.
12. A second identical ingestion makes no unnecessary historical API calls and creates no duplicates.
13. Stored data survives application restarts (session dispose and engine reset).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db import get_engine, reset_engine, session_scope
from app.domain.tables import (
    BenchmarkCacheRecord,
    CandleConflictAudit,
    DatasetProvenanceRecord,
    IngestionRun,
    MarketCandle,
    RawResponseArtifact,
)
from app.integrations.http import HttpResult
from app.market.storage import (
    ASIA_KOLKATA,
    MarketDataStorageService,
    normalize_candle_record,
    parse_iso_or_epoch_to_ist,
)
from app.settings import REPO_ROOT


class MockHistoricalCaller:
    """Mock HTTP caller for Groww historical candles."""

    def __init__(self, candle_generator=None):
        self.call_count = 0
        self.requested_params = []
        self.candle_generator = candle_generator

    def send(self, method: str, url: str, headers: dict, json_body=None, timeout: float = 10.0) -> HttpResult:
        self.call_count += 1
        # Extract params from url
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(url).query)
        params = {k: v[0] for k, v in query.items()}
        self.requested_params.append(params)

        start_str = params.get("start_time", "2026-10-05 09:15:00")
        end_str = params.get("end_time", "2026-10-05 15:30:00")

        if self.candle_generator:
            candles = self.candle_generator(start_str, end_str)
        else:
            # Default: 25 regular bars for requested start_str date
            from app.market.verified_history import STANDARD_SESSION_START_TIMES
            day_str = start_str[:10]
            candles = [
                [f"{day_str} {t_str}", 25000.0 + i, 25010.0 + i, 24990.0 + i, 25005.0 + i, 1000 + i, 500]
                for i, t_str in enumerate(STANDARD_SESSION_START_TIMES)
            ]

        body = {
            "status": "SUCCESS",
            "payload": {
                "candles": candles
            }
        }
        return HttpResult(status_code=200, body=body, text=json.dumps(body))


@pytest.fixture(autouse=True)
def clean_market_tables():
    """Ensure market data tables are clean before and after each test."""
    with session_scope() as s:
        s.execute(text("TRUNCATE market_candles, raw_response_artifacts, candle_conflict_audit, ingestion_runs, dataset_provenance, benchmark_cache RESTART IDENTITY CASCADE"))
    yield
    with session_scope() as s:
        s.execute(text("TRUNCATE market_candles, raw_response_artifacts, candle_conflict_audit, ingestion_runs, dataset_provenance, benchmark_cache RESTART IDENTITY CASCADE"))


def test_persist_normalized_candles_and_unique_key():
    """Requirement 1 & 3: Persist normalized Groww candles and enforce unique (symbol, interval, timestamp) key."""
    candles = [
        ["2026-10-05 09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, 1200.0, 500.0],
        ["2026-10-05 09:30:00", 25020.0, 25070.0, 25010.0, 25060.0, 1500.0, 520.0],
    ]

    with session_scope() as s:
        res = MarketDataStorageService.persist_normalized_candles(
            candles, symbol="NSE-NIFTY", interval="15minute", session=s
        )
        assert res["inserted"] == 2
        assert res["skipped_identical"] == 0
        assert res["conflicts_detected"] == 0

    # Query stored candles
    start_dt = datetime(2026, 10, 5, 9, 0, tzinfo=ASIA_KOLKATA)
    end_dt = datetime(2026, 10, 5, 10, 0, tzinfo=ASIA_KOLKATA)
    stored = MarketDataStorageService.get_stored_candles("NSE-NIFTY", "15minute", start_dt, end_dt)
    assert len(stored) == 2
    assert stored[0]["open"] == 25000.0
    assert stored[0]["session_type"] == "REGULAR"
    assert stored[1]["close"] == 25060.0

    # Direct database insertion with identical key MUST violate unique constraint
    with pytest.raises(IntegrityError):
        with session_scope() as s:
            dup = MarketCandle(
                symbol="NSE-NIFTY",
                interval="15minute",
                timestamp=parse_iso_or_epoch_to_ist("2026-10-05 09:15:00"),
                open=Decimal("25000.0"),
                high=Decimal("25050.0"),
                low=Decimal("24980.0"),
                close=Decimal("25020.0"),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            s.add(dup)
            s.flush()


def test_raw_api_artifact_storage_and_sha256(tmp_path):
    """Requirement 2: Store raw API responses as immutable artifacts with SHA256 recorded in DB."""
    raw_payload = b'{"status": "SUCCESS", "payload": {"candles": [["2026-10-05 09:15:00", 25000, 25050, 24980, 25020]]}}'
    expected_sha = hashlib.sha256(raw_payload).hexdigest()

    start_dt = datetime(2026, 10, 5, 9, 15, tzinfo=ASIA_KOLKATA)
    end_dt = datetime(2026, 10, 5, 15, 30, tzinfo=ASIA_KOLKATA)

    with session_scope() as s:
        artifact = MarketDataStorageService.store_raw_api_artifact(
            provider="groww",
            symbol="NSE-NIFTY",
            candle_interval="15minute",
            requested_start=start_dt,
            requested_end=end_dt,
            raw_bytes=raw_payload,
            candle_count=1,
            destination_dir=tmp_path,
            session=s,
        )
        assert artifact.artifact_id == expected_sha
        assert artifact.sha256 == expected_sha
        assert artifact.raw_byte_count == len(raw_payload)

    # Verify physical file on disk
    saved_file = tmp_path / f"{expected_sha}.json"
    assert saved_file.is_file()
    assert saved_file.read_bytes() == raw_payload

    # Calling again with same payload is idempotent (no duplicate DB row, no file error)
    with session_scope() as s:
        artifact2 = MarketDataStorageService.store_raw_api_artifact(
            provider="groww",
            symbol="NSE-NIFTY",
            candle_interval="15minute",
            requested_start=start_dt,
            requested_end=end_dt,
            raw_bytes=raw_payload,
            candle_count=1,
            destination_dir=tmp_path,
            session=s,
        )
        assert artifact2.artifact_id == expected_sha


def test_idempotent_ingestion_and_conflict_audit():
    """Requirement 4 & 7: Idempotent ingestion and conflict audit trail."""
    # First ingestion
    candles_v1 = [
        ["2026-10-05 09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, 1000.0],
    ]
    with session_scope() as s:
        r1 = MarketDataStorageService.persist_normalized_candles(
            candles_v1, "NSE-NIFTY", "15minute", session=s
        )
        assert r1["inserted"] == 1

    # Second ingestion with IDENTICAL data -> idempotent skip
    with session_scope() as s:
        r2 = MarketDataStorageService.persist_normalized_candles(
            candles_v1, "NSE-NIFTY", "15minute", session=s
        )
        assert r2["inserted"] == 0
        assert r2["skipped_identical"] == 1
        assert r2["conflicts_detected"] == 0

    # Third ingestion with CONFLICTING data (different close price)
    candles_conflicting = [
        ["2026-10-05 09:15:00", 25000.0, 25050.0, 24980.0, 25100.0, 1000.0],  # Close altered to 25100.0
    ]
    with session_scope() as s:
        r3 = MarketDataStorageService.persist_normalized_candles(
            candles_conflicting, "NSE-NIFTY", "15minute", session=s
        )
        assert r3["conflicts_detected"] == 1

    # Verify audit record in candle_conflict_audit
    with session_scope() as s:
        conflicts = s.execute(select(CandleConflictAudit)).scalars().all()
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.symbol == "NSE-NIFTY"
        assert c.existing_ohlcv["close"] == 25020.0
        assert c.incoming_ohlcv["close"] == 25100.0
        assert "CONFLICT" in c.resolution or "RETAIN" in c.resolution


def test_second_identical_ingestion_makes_zero_api_calls():
    """Requirement 5, 6, & 12: Ingestion makes zero API calls and no duplicates on identical range."""
    # Define a 1-day range (25 bars)
    start_time = "2026-10-05 09:15:00"
    end_time = "2026-10-05 15:30:00"

    caller = MockHistoricalCaller()

    # Run 1: Initially missing, should make 1 API call
    res1 = MarketDataStorageService.ingest_groww_history_incremental(
        symbol="NSE-NIFTY",
        interval="15minute",
        start_time=start_time,
        end_time=end_time,
        caller=caller,
        access_token="test-token",
    )
    assert res1["ok"] is True
    assert res1["api_calls_made"] == 1
    assert res1["candles_ingested"] == 25
    assert caller.call_count == 1

    # Verify candles stored
    start_dt = parse_iso_or_epoch_to_ist(start_time)
    end_dt = parse_iso_or_epoch_to_ist(end_time)
    stored = MarketDataStorageService.get_stored_candles("NSE-NIFTY", "15minute", start_dt, end_dt)
    assert len(stored) == 25

    # Run 2: Exact same range requested again -> MUST MAKE ZERO API CALLS!
    res2 = MarketDataStorageService.ingest_groww_history_incremental(
        symbol="NSE-NIFTY",
        interval="15minute",
        start_time=start_time,
        end_time=end_time,
        caller=caller,
        access_token="test-token",
    )
    assert res2["ok"] is True
    assert res2["status"] == "ALREADY_STORED"
    assert res2["api_calls_made"] == 0
    assert res2["candles_ingested"] == 0
    # Caller call count MUST remain 1!
    assert caller.call_count == 1

    # Verify no duplicates were created
    stored_after = MarketDataStorageService.get_stored_candles("NSE-NIFTY", "15minute", start_dt, end_dt)
    assert len(stored_after) == 25


def test_incremental_partial_ingestion_fetches_only_missing_gap():
    """Requirement 5: On subsequent runs, fetch only missing historical ranges."""
    # First: Day 1 (Oct 5) is ingested
    caller = MockHistoricalCaller()

    MarketDataStorageService.ingest_groww_history_incremental(
        symbol="NSE-NIFTY",
        interval="15minute",
        start_time="2026-10-05 09:15:00",
        end_time="2026-10-05 15:30:00",
        caller=caller,
        access_token="test-token",
    )
    assert caller.call_count == 1

    # Now request 2 days: Oct 5 to Oct 6
    # Day 1 is already in DB. Only Day 2 (Oct 6) should be fetched!
    res = MarketDataStorageService.ingest_groww_history_incremental(
        symbol="NSE-NIFTY",
        interval="15minute",
        start_time="2026-10-05 09:15:00",
        end_time="2026-10-06 15:30:00",
        caller=caller,
        access_token="test-token",
    )
    assert res["ok"] is True
    # Exactly 1 additional API call should have been made for the missing day
    assert res["api_calls_made"] == 1
    assert caller.call_count == 2
    # Verify the second API call requested Oct 6
    last_req = caller.requested_params[-1]
    assert "2026-10-06" in last_req["start_time"]


def test_resumable_ingestion_run_after_failure():
    """Requirement 8: Support resumable ingestion after failures."""
    start_dt = datetime(2026, 10, 5, 9, 15, tzinfo=ASIA_KOLKATA)
    end_dt = datetime(2026, 10, 6, 15, 30, tzinfo=ASIA_KOLKATA)

    missing_ranges = [
        (datetime(2026, 10, 5, 9, 15, tzinfo=ASIA_KOLKATA), datetime(2026, 10, 5, 15, 30, tzinfo=ASIA_KOLKATA)),
        (datetime(2026, 10, 6, 9, 15, tzinfo=ASIA_KOLKATA), datetime(2026, 10, 6, 15, 30, tzinfo=ASIA_KOLKATA)),
    ]

    with session_scope() as s:
        run = MarketDataStorageService.start_ingestion_run(
            "groww", "NSE-NIFTY", "15minute", start_dt, end_dt, missing_ranges, session=s
        )
        assert run.status == "IN_PROGRESS"
        assert run.total_chunks == 2
        assert run.completed_chunks == 0

        # Simulate first chunk completing
        run.completed_chunks = 1
        run.completed_ranges = [f"{missing_ranges[0][0].isoformat()}_{missing_ranges[0][1].isoformat()}"]
        run.status = "FAILED"  # Process died
        run.error_message = "Simulated network failure on chunk 2"

    # Now resume
    with session_scope() as s:
        resumed_run = MarketDataStorageService.start_ingestion_run(
            "groww", "NSE-NIFTY", "15minute", start_dt, end_dt, missing_ranges, session=s
        )
        # Should resume existing run and keep completed chunks
        assert resumed_run.run_id == run.run_id
        assert resumed_run.completed_chunks == 1
        assert len(resumed_run.completed_ranges) == 1


def test_dataset_provenance_and_quality_checks_persistence():
    """Requirement 9: Persist data-quality checks, dataset versions, and provenance."""
    dataset_id = "test_dataset_provenance_hash_1234567890abcdef"
    quality_report = {
        "geometric_consistency": True,
        "price_positivity": True,
        "missing_bars_count": 0,
        "complete_sessions": 10,
        "incomplete_sessions": 0,
    }
    raw_hashes = ["hash_chunk_1", "hash_chunk_2"]

    start_dt = datetime(2026, 10, 5, 9, 15, tzinfo=ASIA_KOLKATA)
    end_dt = datetime(2026, 10, 16, 15, 30, tzinfo=ASIA_KOLKATA)

    with session_scope() as s:
        rec = MarketDataStorageService.save_dataset_provenance(
            dataset_id=dataset_id,
            version="m22-v1",
            symbol="NSE-NIFTY",
            interval="15minute",
            start_time=start_dt,
            end_time=end_dt,
            candle_count=250,
            quality_report=quality_report,
            source_artifact_hashes=raw_hashes,
            verification_level="LEVEL_2",
            verification_status="VERIFIED",
            session=s,
        )
        assert rec.dataset_id == dataset_id

    # Retrieve and verify
    provenance = MarketDataStorageService.get_dataset_provenance(dataset_id)
    assert provenance is not None
    assert provenance["version"] == "m22-v1"
    assert provenance["candle_count"] == 250
    assert provenance["quality_report"]["geometric_consistency"] is True
    assert provenance["source_artifact_hashes"] == raw_hashes


def test_benchmark_caching_and_invalidation():
    """Requirement 10 & 11: Cache benchmark results and invalidate when inputs change."""
    dataset_id = "test_dataset_123"
    model_version = "v6-logreg-htf-1"
    feature_config = {"lookback": 5, "htf_context": "1H"}
    target = "O2O"
    eval_settings = {"initial_train": 50, "val_size": 25, "test_size": 25, "embargo": 1}
    metrics = {
        "accuracy": 0.5200,
        "brier_score": 0.2981,
        "prior_brier": 0.2547,
        "bss_percent": -17.04,
        "net_return_5bps": -0.098,
    }

    # 1. Cache result
    with session_scope() as s:
        MarketDataStorageService.cache_benchmark_result(
            dataset_id=dataset_id,
            model_version=model_version,
            feature_config=feature_config,
            target=target,
            eval_settings=eval_settings,
            metrics=metrics,
            session=s,
        )

    # 2. Cache hit
    cached = MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_version,
        feature_config=feature_config,
        target=target,
        eval_settings=eval_settings,
    )
    assert cached is not None
    assert cached["accuracy"] == 0.5200
    assert cached["brier_score"] == 0.2981

    # 3. Cache miss for differing inputs (e.g. target = C2C)
    miss = MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_version,
        feature_config=feature_config,
        target="C2C",
        eval_settings=eval_settings,
    )
    assert miss is None

    # 4. Invalidation
    with session_scope() as s:
        count = MarketDataStorageService.invalidate_benchmark_cache(
            dataset_id=dataset_id, reason="Dataset updated with new bars", session=s
        )
        assert count == 1

    # 5. After invalidation, should return None (miss)
    invalidated_hit = MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_version,
        feature_config=feature_config,
        target=target,
        eval_settings=eval_settings,
    )
    assert invalidated_hit is None


def test_data_survives_application_restarts():
    """Requirement 13: Stored data survives application restarts."""
    candles = [
        ["2026-10-05 09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, 1000.0],
        ["2026-10-05 09:30:00", 25020.0, 25070.0, 25010.0, 25060.0, 1100.0],
    ]
    with session_scope() as s:
        MarketDataStorageService.persist_normalized_candles(
            candles, "NSE-NIFTY", "15minute", session=s
        )

    # Simulate full engine / connection pool reset (application restart)
    reset_engine()

    # Query again from a fresh connection and session
    start_dt = datetime(2026, 10, 5, 9, 0, tzinfo=ASIA_KOLKATA)
    end_dt = datetime(2026, 10, 5, 10, 0, tzinfo=ASIA_KOLKATA)
    reloaded = MarketDataStorageService.get_stored_candles("NSE-NIFTY", "15minute", start_dt, end_dt)
    assert len(reloaded) == 2
    assert reloaded[0]["open"] == 25000.0
    assert reloaded[1]["close"] == 25060.0


def test_storage_api_endpoints_and_cache(client):
    """Test persistent storage API endpoints and cache invalidation via TestClient."""
    from tests.conftest import login
    csrf_token = login(client)

    # 1. Insert candles via service
    candles = [
        ["2026-10-05 09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, 1000.0],
        ["2026-10-05 09:30:00", 25020.0, 25070.0, 25010.0, 25060.0, 1100.0],
    ]
    with session_scope() as s:
        MarketDataStorageService.persist_normalized_candles(
            candles, "NSE-NIFTY", "15minute", session=s
        )

    # 2. Query stored candles endpoint
    resp = client.get(
        "/api/history/storage/candles",
        params={
            "symbol": "NSE-NIFTY",
            "interval": "15minute",
            "start_time": "2026-10-05 09:15:00",
            "end_time": "2026-10-05 15:30:00",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["candles"][0]["open"] == 25000.0

    # 3. Store provenance and query endpoint
    dataset_id = "test_provenance_api_123"
    with session_scope() as s:
        MarketDataStorageService.save_dataset_provenance(
            dataset_id=dataset_id,
            version="m23-p1",
            symbol="NSE-NIFTY",
            interval="15minute",
            start_time=datetime(2026, 10, 5, 9, 15, tzinfo=ASIA_KOLKATA),
            end_time=datetime(2026, 10, 16, 15, 30, tzinfo=ASIA_KOLKATA),
            candle_count=250,
            quality_report={"complete": True},
            source_artifact_hashes=["sha1"],
            session=s,
        )

    resp_prov = client.get(f"/api/history/storage/provenance/{dataset_id}")
    assert resp_prov.status_code == 200, resp_prov.text
    assert resp_prov.json()["ok"] is True
    assert resp_prov.json()["provenance"]["version"] == "m23-p1"

    # 4. Cache benchmark and invalidate via endpoint
    with session_scope() as s:
        MarketDataStorageService.cache_benchmark_result(
            dataset_id=dataset_id,
            model_version="v6-test",
            feature_config={"test": 1},
            target="O2O",
            eval_settings={"step": 25},
            metrics={"acc": 0.52},
            session=s,
        )

    inv_resp = client.post(
        "/api/history/storage/cache/invalidate",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "dataset_id": dataset_id,
            "reason": "Test invalidation via API",
        },
    )
    assert inv_resp.status_code == 200, inv_resp.text
    assert inv_resp.json()["ok"] is True
    assert inv_resp.json()["invalidated_count"] == 1

