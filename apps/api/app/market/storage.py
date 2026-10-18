"""Milestone M23 Preparation: Persistent Market Data Storage, Audit, and Benchmark Cache.

Provides:
- Durable database persistence of normalized Groww candles with unique (symbol, interval, timestamp) keys.
- Immutable filesystem storage of raw API responses, with SHA-256 hashes and file paths recorded in the database.
- Incremental and idempotent ingestion (subsequent runs fetch only missing historical ranges; 0 API calls if already stored).
- Conflict detection and auditing (retaining complete bars over partial bars, logging conflicting OHLCV).
- Resumable ingestion runs surviving failures and restarts.
- Dataset provenance and quality check persistence.
- Benchmark result caching keyed by dataset version/hash, model version, features, target, and evaluation settings.
- Cache invalidation upon input changes.
- Cross-restart data survival.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.domain.tables import (
    BenchmarkCacheRecord,
    CandleConflictAudit,
    DatasetProvenanceRecord,
    IngestionRun,
    MarketCandle,
    RawResponseArtifact,
    utcnow,
)
from app.integrations.groww import historical_candles_url, read_historical_candles
from app.market.schemas import IST, require_aware
from app.market.session_intelligence import NSE_BSE_HOLIDAYS_2026
from app.market.verified_history import STANDARD_SESSION_START_TIMES
from app.settings import REPO_ROOT

log = logging.getLogger("imm.market.storage")
ASIA_KOLKATA = ZoneInfo("Asia/Kolkata")


def parse_iso_or_epoch_to_ist(val: Any) -> datetime:
    """Parse integer/float epoch or ISO string into an aware Asia/Kolkata datetime."""
    if isinstance(val, (int, float)):
        # If timestamp is in milliseconds (> 1e11), convert to seconds
        ts_sec = val / 1000.0 if val > 1e11 else float(val)
        return datetime.fromtimestamp(ts_sec, tz=timezone.utc).astimezone(ASIA_KOLKATA)
    elif isinstance(val, str):
        # Format like "2026-10-05 09:15:00" or ISO
        cleaned = val.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=ASIA_KOLKATA)
        return dt.astimezone(ASIA_KOLKATA)
    elif isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=ASIA_KOLKATA)
        return val.astimezone(ASIA_KOLKATA)
    raise ValueError(f"Unsupported timestamp value: {val!r}")


def normalize_candle_record(
    item: dict[str, Any] | list[Any],
    symbol: str,
    interval: str,
    raw_artifact_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a raw candle (dict or list format) into standard internal schema."""
    if isinstance(item, (list, tuple)):
        # Groww array format: [time, open, high, low, close, volume, open_interest]
        ts_val = item[0]
        o = float(item[1])
        h = float(item[2])
        l = float(item[3])
        c = float(item[4])
        v = float(item[5]) if len(item) > 5 and item[5] is not None else 0.0
        oi = float(item[6]) if len(item) > 6 and item[6] is not None else 0.0
    elif isinstance(item, dict):
        ts_val = item.get("timestamp") or item.get("time")
        o = float(item["open"])
        h = float(item["high"])
        l = float(item["low"])
        c = float(item["close"])
        v = float(item.get("volume", 0.0) or 0.0)
        oi = float(item.get("open_interest", 0.0) or 0.0)
    else:
        raise ValueError(f"Unrecognized candle type: {type(item)}")

    dt_ist = parse_iso_or_epoch_to_ist(ts_val)
    time_str = dt_ist.strftime("%H:%M:%S")

    # Session classification
    if time_str in STANDARD_SESSION_START_TIMES:
        session_type = "REGULAR"
    elif "09:00:00" <= time_str < "09:15:00":
        session_type = "PRE_MARKET"
    elif "15:30:00" <= time_str <= "15:45:00":
        session_type = "POST_MARKET"
    else:
        session_type = "SPECIAL"

    return {
        "symbol": symbol,
        "interval": interval,
        "timestamp": dt_ist,
        "open": Decimal(f"{o:.4f}"),
        "high": Decimal(f"{h:.4f}"),
        "low": Decimal(f"{l:.4f}"),
        "close": Decimal(f"{c:.4f}"),
        "volume": Decimal(f"{v:.4f}"),
        "open_interest": Decimal(f"{oi:.4f}"),
        "session_type": session_type,
        "is_complete": True,
        "raw_artifact_id": raw_artifact_id,
    }


class MarketDataStorageService:
    """Comprehensive persistence, incremental ingestion, auditing, and benchmark caching service."""

    @staticmethod
    def store_raw_api_artifact(
        provider: str,
        symbol: str,
        candle_interval: str,
        requested_start: datetime,
        requested_end: datetime,
        raw_bytes: bytes,
        candle_count: int = 0,
        destination_dir: Path | None = None,
        session: Session | None = None,
    ) -> RawResponseArtifact:
        """Persist raw provider bytes to an immutable file and record its metadata in DB."""
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        target_dir = destination_dir or (REPO_ROOT / "var" / "history" / "quarantine")
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{raw_sha}.json"

        # Write immutable artifact to disk if not exists
        if not file_path.exists():
            file_path.write_bytes(raw_bytes)

        # Database recording
        def _record(s: Session) -> RawResponseArtifact:
            existing = s.execute(
                select(RawResponseArtifact).where(RawResponseArtifact.artifact_id == raw_sha)
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            artifact = RawResponseArtifact(
                artifact_id=raw_sha,
                provider=provider,
                symbol=symbol,
                candle_interval=candle_interval,
                requested_start=requested_start,
                requested_end=requested_end,
                file_path=str(file_path),
                sha256=raw_sha,
                raw_byte_count=len(raw_bytes),
                candle_count=candle_count,
                created_at=utcnow(),
            )
            s.add(artifact)
            s.flush()
            return artifact

        if session is not None:
            return _record(session)
        with session_scope() as s:
            return _record(s)

    @staticmethod
    def persist_normalized_candles(
        candles: list[dict[str, Any] | list[Any]],
        symbol: str,
        interval: str,
        raw_artifact_id: str | None = None,
        session: Session | None = None,
    ) -> dict[str, int]:
        """Ingest candles incrementally and idempotently, detecting and logging conflicts."""
        def _persist(s: Session) -> dict[str, int]:
            inserted = 0
            skipped = 0
            conflicts = 0

            for raw in candles:
                norm = normalize_candle_record(raw, symbol, interval, raw_artifact_id)
                ts = norm["timestamp"]

                existing = s.execute(
                    select(MarketCandle).where(
                        MarketCandle.symbol == symbol,
                        MarketCandle.interval == interval,
                        MarketCandle.timestamp == ts,
                    )
                ).scalar_one_or_none()

                if existing is None:
                    # New candle - insert
                    candle = MarketCandle(
                        symbol=norm["symbol"],
                        interval=norm["interval"],
                        timestamp=norm["timestamp"],
                        open=norm["open"],
                        high=norm["high"],
                        low=norm["low"],
                        close=norm["close"],
                        volume=norm["volume"],
                        open_interest=norm["open_interest"],
                        session_type=norm["session_type"],
                        is_complete=norm["is_complete"],
                        raw_artifact_id=norm["raw_artifact_id"],
                        created_at=utcnow(),
                        updated_at=utcnow(),
                    )
                    s.add(candle)
                    inserted += 1
                else:
                    # Compare OHLCV for equality within epsilon
                    eps = Decimal("0.001")
                    diff_o = abs(existing.open - norm["open"])
                    diff_h = abs(existing.high - norm["high"])
                    diff_l = abs(existing.low - norm["low"])
                    diff_c = abs(existing.close - norm["close"])

                    if diff_o < eps and diff_h < eps and diff_l < eps and diff_c < eps:
                        # Identical duplicate: idempotent skip
                        skipped += 1
                    else:
                        # Conflict detected: preserve audit trail
                        conflicts += 1
                        existing_ohlcv = {
                            "open": float(existing.open),
                            "high": float(existing.high),
                            "low": float(existing.low),
                            "close": float(existing.close),
                            "volume": float(existing.volume or 0.0),
                            "is_complete": existing.is_complete,
                        }
                        incoming_ohlcv = {
                            "open": float(norm["open"]),
                            "high": float(norm["high"]),
                            "low": float(norm["low"]),
                            "close": float(norm["close"]),
                            "volume": float(norm["volume"] or 0.0),
                            "is_complete": norm["is_complete"],
                        }

                        # Reconciliation rule: if existing is incomplete and incoming is complete, update
                        if not existing.is_complete and norm["is_complete"]:
                            resolution = "UPDATED_COMPLETE_SUPERSEDES_PARTIAL"
                            reason = "Incoming candle is complete regular bar; superseded partial bar"
                            existing.open = norm["open"]
                            existing.high = norm["high"]
                            existing.low = norm["low"]
                            existing.close = norm["close"]
                            existing.volume = norm["volume"]
                            existing.is_complete = True
                            existing.raw_artifact_id = norm["raw_artifact_id"]
                            existing.updated_at = utcnow()
                        else:
                            resolution = "RETAIN_EXISTING_COMPLETE"
                            reason = "Existing complete bar retained; incoming conflicting bar logged"

                        audit_entry = CandleConflictAudit(
                            symbol=symbol,
                            interval=interval,
                            timestamp=ts,
                            existing_ohlcv=existing_ohlcv,
                            incoming_ohlcv=incoming_ohlcv,
                            resolution=resolution,
                            reason=reason,
                            incoming_artifact_id=raw_artifact_id,
                            created_at=utcnow(),
                        )
                        s.add(audit_entry)

            s.flush()
            return {
                "inserted": inserted,
                "skipped_identical": skipped,
                "conflicts_detected": conflicts,
                "total": len(candles),
            }

        if session is not None:
            return _persist(session)
        with session_scope() as s:
            return _persist(s)

    @staticmethod
    def get_stored_candles(
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        regular_only: bool = True,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Query stored candles from the database ordered chronologically."""
        if isinstance(start_time, str):
            start_time = parse_iso_or_epoch_to_ist(start_time)
        if isinstance(end_time, str):
            end_time = parse_iso_or_epoch_to_ist(end_time)

        def _query(s: Session) -> list[dict[str, Any]]:
            stmt = select(MarketCandle).where(
                MarketCandle.symbol == symbol,
                MarketCandle.interval == interval,
                MarketCandle.timestamp >= start_time,
                MarketCandle.timestamp <= end_time,
            )
            if regular_only:
                stmt = stmt.where(MarketCandle.session_type == "REGULAR")
            stmt = stmt.order_by(MarketCandle.timestamp.asc())
            rows = s.execute(stmt).scalars().all()

            results = []
            for r in rows:
                results.append({
                    "id": r.id,
                    "symbol": r.symbol,
                    "interval": r.interval,
                    "timestamp": r.timestamp.astimezone(ASIA_KOLKATA).strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp_iso": r.timestamp.isoformat(),
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": float(r.volume or 0.0),
                    "open_interest": float(r.open_interest or 0.0),
                    "session_type": r.session_type,
                    "is_complete": r.is_complete,
                    "raw_artifact_id": r.raw_artifact_id,
                })
            return results

        if session is not None:
            return _query(session)
        with session_scope() as s:
            return _query(s)

    @staticmethod
    def find_missing_historical_ranges(
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        session: Session | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """Identify missing sub-ranges that need to be fetched from the historical API.

        Examines all expected continuous sessions between start_time and end_time.
        If all expected bars are already present and complete in the DB, returns [].
        """
        def _find(s: Session) -> list[tuple[datetime, datetime]]:
            # 1. Fetch all existing stored timestamps in the window
            stmt = select(MarketCandle.timestamp).where(
                MarketCandle.symbol == symbol,
                MarketCandle.interval == interval,
                MarketCandle.timestamp >= start_time,
                MarketCandle.timestamp <= end_time,
                MarketCandle.session_type == "REGULAR",
            )
            stored_ts = set(
                ts.astimezone(ASIA_KOLKATA).strftime("%Y-%m-%d %H:%M:%S")
                for ts in s.execute(stmt).scalars().all()
            )

            # 2. Generate expected regular 15m session timestamps
            cur_date = start_time.astimezone(ASIA_KOLKATA).date()
            final_date = end_time.astimezone(ASIA_KOLKATA).date()

            missing_bars: list[datetime] = []
            while cur_date <= final_date:
                # Skip weekends
                if cur_date.weekday() < 5 and cur_date not in NSE_BSE_HOLIDAYS_2026:
                    for t_str in STANDARD_SESSION_START_TIMES:
                        expected_dt = datetime.strptime(
                            f"{cur_date} {t_str}", "%Y-%m-%d %H:%M:%S"
                        ).replace(tzinfo=ASIA_KOLKATA)

                        if start_time <= expected_dt <= end_time:
                            key = expected_dt.strftime("%Y-%m-%d %H:%M:%S")
                            if key not in stored_ts:
                                missing_bars.append(expected_dt)
                cur_date += timedelta(days=1)

            if not missing_bars:
                return []

            # 3. Group contiguous missing bars into contiguous chunks
            missing_bars.sort()
            chunks: list[tuple[datetime, datetime]] = []
            chunk_start = missing_bars[0]
            chunk_end = missing_bars[0]

            for b in missing_bars[1:]:
                # If within 4 days (handling weekend gap in contiguous missing chunk)
                if (b - chunk_end) <= timedelta(days=4):
                    chunk_end = b
                else:
                    # Close chunk: expand start to 09:15:00 and end to 15:30:00 for clean API bounds
                    c_s = chunk_start.replace(hour=9, minute=15, second=0)
                    c_e = chunk_end.replace(hour=15, minute=30, second=0)
                    chunks.append((c_s, c_e))
                    chunk_start = b
                    chunk_end = b

            c_s = chunk_start.replace(hour=9, minute=15, second=0)
            c_e = chunk_end.replace(hour=15, minute=30, second=0)
            chunks.append((c_s, c_e))
            return chunks

        if session is not None:
            return _find(session)
        with session_scope() as s:
            return _find(s)

    @staticmethod
    def start_ingestion_run(
        provider: str,
        symbol: str,
        interval: str,
        requested_start: datetime,
        requested_end: datetime,
        missing_ranges: list[tuple[datetime, datetime]],
        session: Session | None = None,
    ) -> IngestionRun:
        """Create or resume an IngestionRun tracking record."""
        run_id = hashlib.sha256(
            f"{provider}_{symbol}_{interval}_{requested_start.isoformat()}_{requested_end.isoformat()}".encode()
        ).hexdigest()

        ranges_json = [
            {"start": s.isoformat(), "end": e.isoformat()} for s, e in missing_ranges
        ]

        def _create(s: Session) -> IngestionRun:
            existing = s.execute(
                select(IngestionRun).where(IngestionRun.run_id == run_id)
            ).scalar_one_or_none()

            if existing is not None:
                # Update missing ranges if resuming
                existing.missing_ranges = ranges_json
                existing.total_chunks = len(ranges_json)
                existing.updated_at = utcnow()
                s.flush()
                return existing

            run = IngestionRun(
                run_id=run_id,
                provider=provider,
                symbol=symbol,
                interval=interval,
                requested_start=requested_start,
                requested_end=requested_end,
                status="COMPLETED" if not missing_ranges else "IN_PROGRESS",
                total_chunks=len(ranges_json),
                completed_chunks=0,
                missing_ranges=ranges_json,
                completed_ranges=[],
                candles_ingested=0,
                conflicts_detected=0,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            s.add(run)
            s.flush()
            return run

        if session is not None:
            return _create(session)
        with session_scope() as s:
            return _create(s)

    @classmethod
    def ingest_groww_history_incremental(
        cls,
        symbol: str,
        interval: str,
        start_time: str | datetime,
        end_time: str | datetime,
        caller: Any = None,
        access_token: str | None = None,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Incremental, idempotent Groww historical ingestion.

        Guarantees:
        - NEVER redownloads data that is already stored.
        - If all data is present, makes 0 historical API calls.
        - Only fetches missing sub-ranges.
        - Persists raw responses as immutable files and DB records.
        - Persists normalized candles with conflict detection.
        - Survives restarts and supports resumption.
        """
        start_dt = parse_iso_or_epoch_to_ist(start_time)
        end_dt = parse_iso_or_epoch_to_ist(end_time)

        def _execute(s: Session) -> dict[str, Any]:
            # Step 1: Detect missing ranges
            missing_ranges = cls.find_missing_historical_ranges(symbol, interval, start_dt, end_dt, session=s)

            if not missing_ranges:
                # Entire history is already present! Zero API calls required.
                existing_candles = cls.get_stored_candles(symbol, interval, start_dt, end_dt, session=s)
                return {
                    "ok": True,
                    "status": "ALREADY_STORED",
                    "api_calls_made": 0,
                    "missing_ranges_count": 0,
                    "candles_stored_count": len(existing_candles),
                    "candles_ingested": 0,
                    "conflicts_detected": 0,
                    "candles": existing_candles,
                }

            # Step 2: Initialize or resume ingestion run
            run = cls.start_ingestion_run("groww", symbol, interval, start_dt, end_dt, missing_ranges, session=s)

            if caller is None or not access_token:
                return {
                    "ok": False,
                    "status": "API_CREDENTIALS_REQUIRED_FOR_MISSING_RANGES",
                    "missing_ranges": [{"start": m[0].isoformat(), "end": m[1].isoformat()} for m in missing_ranges],
                    "api_calls_made": 0,
                }

            api_calls = 0
            total_ingested = 0
            total_conflicts = 0

            # Step 3: Fetch ONLY missing ranges
            completed_ranges = list(run.completed_ranges or [])
            for c_start, c_end in missing_ranges:
                range_key = f"{c_start.isoformat()}_{c_end.isoformat()}"
                if range_key in completed_ranges:
                    continue

                params = {
                    "exchange": "NSE",
                    "segment": "CASH",
                    "groww_symbol": symbol if "-" in symbol else f"NSE-{symbol}",
                    "candle_interval": interval,
                    "start_time": c_start.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": c_end.strftime("%Y-%m-%d %H:%M:%S"),
                }

                # External API call
                result = read_historical_candles(caller, access_token, params)
                api_calls += 1

                if result.status_code != 200:
                    run.status = "FAILED"
                    run.error_message = f"API returned status {result.status_code}: {result.text}"
                    s.flush()
                    raise RuntimeError(f"Historical API call failed with status {result.status_code}")

                # Save raw payload as immutable artifact
                raw_bytes = result.text.encode("utf-8")
                parsed_body = result.body or {}
                raw_candles = (
                    parsed_body.get("payload", {}).get("candles")
                    or parsed_body.get("candles")
                    or []
                )

                artifact = cls.store_raw_api_artifact(
                    provider="groww",
                    symbol=symbol,
                    candle_interval=interval,
                    requested_start=c_start,
                    requested_end=c_end,
                    raw_bytes=raw_bytes,
                    candle_count=len(raw_candles),
                    session=s,
                )

                # Persist normalized candles
                persist_res = cls.persist_normalized_candles(
                    candles=raw_candles,
                    symbol=symbol,
                    interval=interval,
                    raw_artifact_id=artifact.artifact_id,
                    session=s,
                )

                total_ingested += persist_res["inserted"]
                total_conflicts += persist_res["conflicts_detected"]

                # Mark chunk completed
                completed_ranges.append(range_key)
                run.completed_ranges = completed_ranges
                run.completed_chunks = len(completed_ranges)
                run.candles_ingested += persist_res["inserted"]
                run.conflicts_detected += persist_res["conflicts_detected"]
                s.flush()

            run.status = "COMPLETED"
            run.updated_at = utcnow()
            s.flush()

            stored_candles = cls.get_stored_candles(symbol, interval, start_dt, end_dt, session=s)
            return {
                "ok": True,
                "status": "INGESTED_INCREMENTAL",
                "api_calls_made": api_calls,
                "missing_ranges_count": len(missing_ranges),
                "candles_ingested": total_ingested,
                "conflicts_detected": total_conflicts,
                "candles_stored_count": len(stored_candles),
                "candles": stored_candles,
            }

        if session is not None:
            return _execute(session)
        with session_scope() as s:
            return _execute(s)

    # -------------------------------------------------------------------------
    # Dataset Provenance & Data-Quality Persistence
    # -------------------------------------------------------------------------
    @staticmethod
    def save_dataset_provenance(
        dataset_id: str,
        version: str,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        candle_count: int,
        quality_report: dict[str, Any],
        source_artifact_hashes: list[str],
        verification_level: str = "LEVEL_2",
        verification_status: str = "VERIFIED",
        session: Session | None = None,
    ) -> DatasetProvenanceRecord:
        """Persist data quality checks and cryptographic provenance for a derived dataset."""
        def _save(s: Session) -> DatasetProvenanceRecord:
            existing = s.execute(
                select(DatasetProvenanceRecord).where(DatasetProvenanceRecord.dataset_id == dataset_id)
            ).scalar_one_or_none()

            if existing is not None:
                existing.version = version
                existing.candle_count = candle_count
                existing.quality_report = quality_report
                existing.source_artifact_hashes = source_artifact_hashes
                existing.verification_level = verification_level
                existing.verification_status = verification_status
                s.flush()
                return existing

            record = DatasetProvenanceRecord(
                dataset_id=dataset_id,
                version=version,
                symbol=symbol,
                interval=interval,
                start_time=start_time,
                end_time=end_time,
                candle_count=candle_count,
                quality_report=quality_report,
                source_artifact_hashes=source_artifact_hashes,
                verification_level=verification_level,
                verification_status=verification_status,
                created_at=utcnow(),
            )
            s.add(record)
            s.flush()
            return record

        if session is not None:
            return _save(session)
        with session_scope() as s:
            return _save(s)

    @staticmethod
    def get_dataset_provenance(
        dataset_id: str,
        session: Session | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve stored dataset provenance and quality report."""
        def _get(s: Session) -> dict[str, Any] | None:
            r = s.execute(
                select(DatasetProvenanceRecord).where(DatasetProvenanceRecord.dataset_id == dataset_id)
            ).scalar_one_or_none()
            if r is None:
                return None
            return {
                "dataset_id": r.dataset_id,
                "version": r.version,
                "symbol": r.symbol,
                "interval": r.interval,
                "start_time": r.start_time.isoformat(),
                "end_time": r.end_time.isoformat(),
                "candle_count": r.candle_count,
                "quality_report": r.quality_report,
                "source_artifact_hashes": r.source_artifact_hashes,
                "verification_level": r.verification_level,
                "verification_status": r.verification_status,
                "created_at": r.created_at.isoformat(),
            }

        if session is not None:
            return _get(session)
        with session_scope() as s:
            return _get(s)

    # -------------------------------------------------------------------------
    # Benchmark Caching & Invalidation
    # -------------------------------------------------------------------------
    @staticmethod
    def compute_benchmark_cache_key(
        dataset_id: str,
        model_version: str,
        feature_config: dict[str, Any],
        target: str,
        eval_settings: dict[str, Any],
    ) -> str:
        """Derive a deterministic SHA-256 cache key from benchmark inputs."""
        payload = {
            "dataset_id": dataset_id,
            "model_version": model_version,
            "feature_config": feature_config,
            "target": target,
            "eval_settings": eval_settings,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def get_cached_benchmark(
        cls,
        dataset_id: str,
        model_version: str,
        feature_config: dict[str, Any],
        target: str,
        eval_settings: dict[str, Any],
        session: Session | None = None,
    ) -> dict[str, Any] | None:
        """Retrieve cached benchmark results if valid."""
        cache_key = cls.compute_benchmark_cache_key(
            dataset_id, model_version, feature_config, target, eval_settings
        )

        def _get(s: Session) -> dict[str, Any] | None:
            record = s.execute(
                select(BenchmarkCacheRecord).where(
                    BenchmarkCacheRecord.cache_key == cache_key,
                    BenchmarkCacheRecord.invalidated == False,  # noqa: E712
                )
            ).scalar_one_or_none()

            if record is None:
                return None

            record.last_accessed_at = utcnow()
            s.flush()
            return record.metrics

        if session is not None:
            return _get(session)
        with session_scope() as s:
            return _get(s)

    @classmethod
    def cache_benchmark_result(
        cls,
        dataset_id: str,
        model_version: str,
        feature_config: dict[str, Any],
        target: str,
        eval_settings: dict[str, Any],
        metrics: dict[str, Any],
        session: Session | None = None,
    ) -> BenchmarkCacheRecord:
        """Store benchmark evaluation metrics in cache."""
        cache_key = cls.compute_benchmark_cache_key(
            dataset_id, model_version, feature_config, target, eval_settings
        )

        def _cache(s: Session) -> BenchmarkCacheRecord:
            existing = s.execute(
                select(BenchmarkCacheRecord).where(BenchmarkCacheRecord.cache_key == cache_key)
            ).scalar_one_or_none()

            if existing is not None:
                existing.metrics = metrics
                existing.invalidated = False
                existing.invalidation_reason = None
                existing.last_accessed_at = utcnow()
                s.flush()
                return existing

            record = BenchmarkCacheRecord(
                cache_key=cache_key,
                dataset_id=dataset_id,
                model_version=model_version,
                feature_config=feature_config,
                target=target,
                eval_settings=eval_settings,
                metrics=metrics,
                invalidated=False,
                created_at=utcnow(),
                last_accessed_at=utcnow(),
            )
            s.add(record)
            s.flush()
            return record

        if session is not None:
            return _cache(session)
        with session_scope() as s:
            return _cache(s)

    @staticmethod
    def invalidate_benchmark_cache(
        dataset_id: str | None = None,
        model_version: str | None = None,
        target: str | None = None,
        cache_key: str | None = None,
        reason: str = "Input parameters or dataset invalidated",
        session: Session | None = None,
    ) -> int:
        """Invalidate benchmark cache records matching filters."""
        def _inv(s: Session) -> int:
            stmt = update(BenchmarkCacheRecord).where(BenchmarkCacheRecord.invalidated == False)  # noqa: E712
            if cache_key is not None:
                stmt = stmt.where(BenchmarkCacheRecord.cache_key == cache_key)
            if dataset_id is not None:
                stmt = stmt.where(BenchmarkCacheRecord.dataset_id == dataset_id)
            if model_version is not None:
                stmt = stmt.where(BenchmarkCacheRecord.model_version == model_version)
            if target is not None:
                stmt = stmt.where(BenchmarkCacheRecord.target == target)

            stmt = stmt.values(invalidated=True, invalidation_reason=reason)
            res = s.execute(stmt)
            s.flush()
            return res.rowcount

        if session is not None:
            return _inv(session)
        with session_scope() as s:
            return _inv(s)
