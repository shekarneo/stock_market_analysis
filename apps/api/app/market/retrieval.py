"""Read-only Groww historical candle retrieval.

The backtesting pages read on 14 Oct 2026 document the request and the
candle array. They do not say whether the timestamp is the bar start or
the bar end, and they do not state a timezone. A successful response is
quarantined. It is not a trusted historical dataset.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from app.features.pipeline import content_hash
from app.integrations.groww import read_historical_candles
from app.market.history import BLOCK_CODE, BLOCK_MESSAGE, HistoryStoreError, provider_symbol, redact
from app.market.quarantine_validation import ingestion_diagnostic, validate_quarantine_payload
from app.market.timestamp_contract import contract as timestamp_contract

QUARANTINE_SCHEMA = "m7-quarantine-1"
CANDLE_INTERVAL = "15minute"


def request_clock(value: datetime) -> str:
    """Documented yyyy-MM-dd HH:mm:ss string. The offset is removed, not interpreted."""
    wall = value.replace(tzinfo=None)
    return wall.strftime("%Y-%m-%d %H:%M:%S")


def candle_query(instrument: str, start: datetime, end: datetime) -> dict[str, str]:
    mapped = provider_symbol(instrument)
    return {
        "exchange": mapped["exchange"],
        "segment": mapped["segment"],
        "groww_symbol": mapped["groww_symbol"],
        "start_time": request_clock(start),
        "end_time": request_clock(end),
        "candle_interval": CANDLE_INTERVAL,
    }


def retrieve_chunk(caller, access_token: str, instrument: str, start: datetime, end: datetime, *, retrieved_at: datetime) -> dict:
    query = candle_query(instrument, start, end)
    try:
        result = read_historical_candles(caller, access_token, query)
    except TimeoutError:
        return _failure("PROVIDER_TIMEOUT", "The Groww historical request timed out. It was not retried.", query, retrieved_at)
    except Exception as exc:
        return _failure("PROVIDER_ERROR", redact(exc.__class__.__name__), query, retrieved_at)
    return classify_historical_response(result, instrument=instrument, query=query, retrieved_at=retrieved_at)


def classify_historical_response(result, *, instrument: str, query: dict, retrieved_at: datetime) -> dict:
    raw = result.raw if isinstance(getattr(result, "raw", b""), (bytes, bytearray)) else b""
    if not raw and result.text:
        raw = result.text.encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest() if raw else None
    if result.status_code == 429:
        return _failure("RATE_LIMITED", "Groww rate-limited the historical read. It was not retried.", query, retrieved_at, result, checksum)
    if result.status_code in {401, 403}:
        return _failure("AUTHENTICATION_FAILED", "Groww rejected the access token.", query, retrieved_at, result, checksum)
    if result.status_code >= 500:
        return _failure("PROVIDER_UNAVAILABLE", "Groww could not serve the historical read. It was not retried.", query, retrieved_at, result, checksum)
    if result.status_code != 200 or not isinstance(result.body, dict):
        return _failure("SCHEMA_MISMATCH", "The historical response was not the documented object.", query, retrieved_at, result, checksum)
    body = result.body
    if body.get("status") == "FAILURE":
        return _failure("PROVIDER_ERROR", "Groww rejected the historical request.", query, retrieved_at, result, checksum)
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    if isinstance(payload, dict) and isinstance(body.get("status"), str):
        payload = {**payload, "status": body["status"]}
    candles = payload.get("candles") if isinstance(payload, dict) else None
    if not isinstance(candles, list):
        return _failure("SCHEMA_MISMATCH", "The documented payload has no candles array.", query, retrieved_at, result, checksum)
    if not candles:
        return _done(
            "EMPTY_CANDLES",
            "Groww returned no candles for the requested range. None were fabricated.",
            query,
            retrieved_at,
            result,
            checksum,
            payload,
            candles,
            numeric_status="EMPTY",
        )
    numeric = _numeric_report(candles)
    if numeric["status"] != "PASS":
        return _done(numeric["code"], numeric["message"], query, retrieved_at, result, checksum, payload, candles, numeric["status"])
    return _done(
        "CANDLE_BOUNDARY_UNVERIFIED",
        "The raw candle response was quarantined. The timestamp timezone and start-versus-end role are not documented, so no trusted candles were stored.",
        query,
        retrieved_at,
        result,
        checksum,
        payload,
        candles,
        "PASS",
    )


class QuarantineStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(self, record: dict) -> dict:
        body = {key: value for key, value in record.items() if key not in {"quarantine_id", "checksum"}}
        digest = content_hash(body)
        artifact = dict(body)
        artifact["quarantine_id"] = digest
        artifact["checksum"] = digest
        self.root.mkdir(parents=True, exist_ok=True)
        path = (self.root / f"{digest}.json").resolve()
        if path.parent != self.root:
            raise HistoryStoreError("UNSAFE_PATH", "The quarantine file would leave its directory.")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        return artifact

    def read(self, quarantine_id: str) -> dict:
        path = (self.root / f"{quarantine_id}.json").resolve()
        if path.parent != self.root or not path.is_file():
            raise HistoryStoreError("NOT_FOUND", "Quarantine record was not found.")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        body = {key: value for key, value in artifact.items() if key not in {"quarantine_id", "checksum"}}
        if content_hash(body) != artifact.get("checksum"):
            raise HistoryStoreError("CHECKSUM_MISMATCH", "Quarantine checksum does not match its contents.")
        return artifact

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(path.stem for path in self.root.glob("*.json"))


def diagnostic_report(record: dict, siblings: list[dict] | None = None) -> dict:
    """Read-only view of a quarantine record. Does not rewrite the file or emit candles."""
    candles = record.get("raw_candles") or []
    timestamps = [row[0] for row in candles if isinstance(row, list) and row and isinstance(row[0], str)]
    observed = timestamps or [item for item in (record.get("first_raw_timestamp"), record.get("last_raw_timestamp")) if isinstance(item, str)]
    facts = timestamp_contract()
    validation = validate_quarantine_payload(record, siblings)
    return {
        "quarantine_id": record.get("quarantine_id"),
        "checksum": record.get("checksum"),
        "raw_body_sha256": record.get("raw_body_sha256"),
        "label": record.get("label"),
        "data_category": "UNVERIFIED_PROVIDER",
        "trusted_dataset_created": False,
        "forecast_eligible": False,
        "instrument": record.get("instrument"),
        "exchange": record.get("exchange"),
        "segment": record.get("segment"),
        "groww_symbol": record.get("groww_symbol"),
        "interval": record.get("interval"),
        "candle_count": record.get("candle_count"),
        "raw_timestamps": timestamps,
        "first_raw_timestamp": record.get("first_raw_timestamp"),
        "last_raw_timestamp": record.get("last_raw_timestamp"),
        "full_timestamp_list_stored": bool(timestamps),
        "response_start_time": record.get("response_start_time"),
        "response_end_time": record.get("response_end_time"),
        "requested_start_sent": record.get("requested_start_sent"),
        "requested_end_sent": record.get("requested_end_sent"),
        "http_status": record.get("http_status"),
        "provider_status": record.get("provider_status"),
        "known": {
            "timestamp_format_documented": facts["timestamp_format_documented"],
            "observed_offset": "ABSENT" if observed and all(_offset_absent(item) for item in observed) else "NOT_OBSERVED",
        },
        "unknown": {
            "timestamp_timezone": facts["timestamp_timezone"],
            "candle_boundary": facts["candle_boundary"],
            "request_boundary": facts["request_boundary"],
            "partial_candles": facts["partial_candles"],
            "session_open_candle": facts["session_open_candle"],
            "session_close_candle": facts["session_close_candle"],
            "index_timestamp_behavior": facts["index_timestamp_behavior"],
        },
        "rejection_code": BLOCK_CODE,
        "rejection_reason": BLOCK_MESSAGE,
        "contract": facts,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "validation": validation,
        "ingestion": ingestion_diagnostic(record, validation),
    }


def _offset_absent(timestamp: str) -> bool:
    return "Z" not in timestamp and "+" not in timestamp and not (len(timestamp) > 19 and timestamp[19] == "-")


def quarantine_record(chunk: dict, *, instrument: str) -> dict:
    retrieval = chunk["retrieval"]
    return {
        "schema_version": QUARANTINE_SCHEMA,
        "label": "UNVERIFIED_PROVIDER",
        "provider": "groww",
        "instrument": instrument,
        "exchange": chunk["query"]["exchange"],
        "segment": chunk["query"]["segment"],
        "groww_symbol": chunk["query"]["groww_symbol"],
        "interval": "M15",
        "candle_interval": chunk["query"]["candle_interval"],
        "requested_start_sent": chunk["query"]["start_time"],
        "requested_end_sent": chunk["query"]["end_time"],
        "retrieved_at": chunk["retrieved_at"],
        "http_status": retrieval["http_status"],
        "provider_status": retrieval["provider_status"],
        "response_start_time": retrieval["response_start_time"],
        "response_end_time": retrieval["response_end_time"],
        "interval_in_minutes": retrieval["interval_in_minutes"],
        "candle_count": retrieval["candle_count"],
        "first_raw_timestamp": retrieval["first_raw_timestamp"],
        "last_raw_timestamp": retrieval["last_raw_timestamp"],
        "raw_candles": chunk.get("raw_candles") or [],
        "raw_body_sha256": retrieval["raw_body_sha256"],
        "numeric_quality": chunk["numeric_quality"],
        "timestamp_timezone": "UNVERIFIED",
        "candle_boundary": "UNVERIFIED",
        "forecast_eligible": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }


def _failure(code: str, message: str, query: dict, retrieved_at: datetime, result=None, checksum: str | None = None) -> dict:
    return _done(code, message, query, retrieved_at, result, checksum, {}, [], "NOT_ASSESSED")


def _done(code, message, query, retrieved_at, result, checksum, payload, candles, numeric_status) -> dict:
    timestamps = [row[0] for row in candles if isinstance(row, list) and row and isinstance(row[0], str)]
    return {
        "code": code,
        "message": message,
        "query": query,
        "retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat(),
        "numeric_quality": numeric_status,
        "retry": False,
        "raw_candles": candles,
        "retrieval": {
            "http_status": None if result is None else result.status_code,
            "provider_status": payload.get("status") if isinstance(payload, dict) else None,
            "response_start_time": payload.get("start_time") if isinstance(payload, dict) else None,
            "response_end_time": payload.get("end_time") if isinstance(payload, dict) else None,
            "interval_in_minutes": payload.get("interval_in_minutes") if isinstance(payload, dict) else None,
            "candle_count": len(candles),
            "first_raw_timestamp": timestamps[0] if timestamps else None,
            "last_raw_timestamp": timestamps[-1] if timestamps else None,
            "raw_body_sha256": checksum,
        },
    }


def _numeric_report(candles: list) -> dict:
    seen: set[str] = set()
    previous: str | None = None
    for row in candles:
        if not isinstance(row, list) or len(row) not in {6, 7}:
            return {"status": "REJECTED", "code": "SCHEMA_MISMATCH", "message": "A documented candle has 6 or 7 fields."}
        timestamp, open_, high, low, close, volume = row[:6]
        if not isinstance(timestamp, str) or not timestamp:
            return {"status": "REJECTED", "code": "SCHEMA_MISMATCH", "message": "The documented candle timestamp is a string."}
        if timestamp in seen:
            return {"status": "REJECTED", "code": "DUPLICATE_TIMESTAMP", "message": "A duplicate raw candle timestamp was rejected."}
        seen.add(timestamp)
        if previous is not None and timestamp < previous:
            return {"status": "REJECTED", "code": "OUT_OF_ORDER", "message": "Raw candle timestamps are not in order. They were not reordered."}
        previous = timestamp
        if any(isinstance(value, bool) for value in (open_, high, low, close, volume)):
            return {"status": "REJECTED", "code": "SCHEMA_MISMATCH", "message": "OHLC values must be numbers."}
        try:
            prices = [float(value) for value in (open_, high, low, close)]
        except (TypeError, ValueError):
            return {"status": "REJECTED", "code": "SCHEMA_MISMATCH", "message": "OHLC values must be numbers."}
        if any(isinstance(value, bool) or not math.isfinite(value) for value in prices):
            return {"status": "REJECTED", "code": "INVALID_OHLC", "message": "A non-finite OHLC value was rejected."}
        open_price, high_price, low_price, close_price = prices
        if high_price < max(open_price, close_price, low_price) or low_price > min(open_price, close_price, high_price):
            return {"status": "REJECTED", "code": "INVALID_OHLC", "message": "A candle failed the OHLC bounds check."}
        if volume is not None:
            try:
                volume_value = float(volume)
            except (TypeError, ValueError):
                return {"status": "REJECTED", "code": "SCHEMA_MISMATCH", "message": "Volume must be a number or null."}
            if volume_value < 0 or not math.isfinite(volume_value):
                return {"status": "REJECTED", "code": "INVALID_VOLUME", "message": "A negative volume was rejected. No candle was stored."}
    return {"status": "PASS", "code": "CANDLE_BOUNDARY_UNVERIFIED", "message": ""}
