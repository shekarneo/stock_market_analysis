"""Historical candle requests, quality reports, and immutable source datasets.

Groww's backtesting page documents get_historical_candles. It does not say
whether the candle timestamp is the bar start or the bar end, and it does not
state a timezone. Those two gaps block ingestion. This module does not invent
either fact, does not call the network, and does not fabricate OHLC rows.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.features.pipeline import build_dataset, content_hash, seal
from app.features.store import DatasetStore
from app.instruments import REMOVED_UNDERLYINGS
from app.market.calendar import CalendarState, ExchangeCalendar
from app.market.fixtures import CLOSED_TEST_DAY, FIXTURE_DAY, fixture_calendar
from app.market.quality import validate_candle
from app.market.schemas import IST, Candle, DataOrigin, require_aware
from app.market.timestamp_contract import contract as timestamp_contract
from app.market.verified_history import requirements_checklist
from app.market.quarantine_validation import MINIMUM_TRUSTED_EVIDENCE
from app.settings import REPO_ROOT

SCHEMA_VERSION = "m6-source-candles-1"
INTERVAL = timedelta(minutes=15)
MAX_CHUNK = timedelta(days=90)
MAX_RANGE = timedelta(days=366)
HISTORY_FLOOR = datetime(2020, 1, 1, tzinfo=IST)
_ID = re.compile(r"^[a-f0-9]{64}$")
_UNSAFE = {"path", "output_path", "artifact_path", "file"}
_SECRET = re.compile(
    r"(?i)bearer\s+\S+|(api[_-]?key|access[_-]?token|token|secret|password)\s*[=:]\s*\S+"
)

DOCUMENTED_SYMBOLS = {
    "NIFTY": {
        "exchange": "NSE",
        "segment": "CASH",
        "groww_symbol": "NSE-NIFTY",
        "evidence": "Groww backtesting page lists NSE-NIFTY as an index symbol example.",
    },
    "SENSEX": {
        "exchange": "BSE",
        "segment": "CASH",
        "groww_symbol": "BSE-SENSEX",
        "evidence": "Groww backtesting page lists BSE-SENSEX as an index symbol example.",
    },
}

BLOCK_CODE = "CANDLE_BOUNDARY_UNVERIFIED"
BLOCK_MESSAGE = (
    "The Groww backtesting candle timestamp is not documented as a bar start or a bar end, "
    "and the timestamp timezone is not documented. A raw response may be quarantined. Trusted candles are not stored."
)


class HistoryStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


def capabilities() -> dict:
    facts = timestamp_contract()
    return {
        "provider": "groww",
        "method": "get_historical_candles",
        "documentation_url": "https://groww.in/trade-api/docs/python-sdk/backtesting",
        "curl_documentation_url": "https://groww.in/trade-api/docs/curl/backtesting",
        "http_method": "GET",
        "http_path": "/v1/historical/candles",
        "request_fields": ["exchange", "segment", "groww_symbol", "start_time", "end_time", "candle_interval"],
        "candle_fields": ["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        "interval": "M15",
        "candle_interval": "15minute",
        "interval_evidence": "Curl backtesting example uses candle_interval=15minute. The limits table includes 15 min.",
        "max_duration_per_request_days": 90,
        "history_available_from": "2020",
        "pagination": "Not documented. Requests longer than 90 days are planned as adjacent chunks and are not sent.",
        "retry_policy": "no_retry",
        "retry_reason": "The reviewed pages do not document a retry rule for this read.",
        "instruments": DOCUMENTED_SYMBOLS,
        "unmapped_instruments": {},
        "timestamp_timezone": facts["timestamp_timezone"],
        "candle_boundary": facts["candle_boundary"],
        "support_response_received": facts["support_response_received"],
        "outstanding_confirmations": facts["outstanding_confirmations"],
        "ingestion_blocked": facts["ingestion_blocked"],
        "volume_for_indices": "UNVERIFIED",
        "volume_note": "The page says volume is present for tradable equities and FNO. It does not say index candles include volume.",
        "adjustment_behavior": "UNVERIFIED",
        "point_in_time_revisions_available": False,
        "authentication": "Bearer access token from the saved Groww integration. This report does not include a token.",
        "licensing": "UNVERIFIED. The backtesting pages read on 14 Oct 2026 do not state a research-use licence.",
        "documentation_read_on": "2026-10-14",
        "rate_limit": "Not stated on the backtesting or changelog pages read on 14 Oct 2026.",
        "source_verification": "DOCUMENTED_RESPONSE_QUARANTINED",
        "market_data_verification": False,
        "ingestion_operational": False,
        "blocking_code": BLOCK_CODE,
        "blocking_reason": BLOCK_MESSAGE,
        "retrieval_note": (
            "A configured Groww integration can send GET /v1/historical/candles. "
            "The raw response is quarantined and is not forecast-eligible."
        ),
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "verified_history": {
            "status": "BLOCKED",
            "code": "CANDLE_BOUNDARY_UNVERIFIED",
            "trusted_dataset_created": False,
            "m2_ran": False,
            "m3_ran": False,
            "m4_ran": False,
            "reason": (
                "No candidate has a documented NIFTY 15-minute timezone, candle boundary, partial-candle rule, "
                "and an accessible credential together. No trusted dataset was created."
            ),
            "requirements": [{"id": item["id"], "status": item["status"]} for item in requirements_checklist()],
            "minimum_evidence": list(MINIMUM_TRUSTED_EVIDENCE),
        },
    }


def provider_symbol(instrument: str) -> dict:
    if instrument in DOCUMENTED_SYMBOLS:
        mapped = dict(DOCUMENTED_SYMBOLS[instrument])
        mapped["instrument"] = instrument
        mapped["silently_aliased"] = False
        return mapped
    if instrument in REMOVED_UNDERLYINGS:
        raise HistoryStoreError(
            "REMOVED_INSTRUMENT",
            f"{instrument} is out of scope. It was not mapped to another instrument.",
        )
    raise HistoryStoreError("UNKNOWN_INSTRUMENT", f"{instrument} is not a supported instrument.")


def validate_request(instrument: str, interval: str, start: datetime, end: datetime) -> dict:
    provider_symbol(instrument)
    if interval != "M15":
        raise HistoryStoreError("UNSUPPORTED_INTERVAL", "The only implemented historical interval is M15.")
    start = require_aware(start, "start")
    end = require_aware(end, "end")
    if end <= start:
        raise HistoryStoreError("INVALID_RANGE", "The end must be after the start.")
    if start < HISTORY_FLOOR:
        raise HistoryStoreError(
            "BEFORE_DOCUMENTED_HISTORY",
            "The reviewed Groww backtesting page says index history is available from 2020.",
        )
    if end - start > MAX_RANGE:
        raise HistoryStoreError("RANGE_TOO_LONG", "A historical request is limited to 366 days.")
    chunks = plan_chunks(start, end)
    return {
        "instrument": instrument,
        "interval": interval,
        "start": start.astimezone(IST).isoformat(),
        "end": end.astimezone(IST).isoformat(),
        "chunks": [
            {"start": left.astimezone(IST).isoformat(), "end": right.astimezone(IST).isoformat()}
            for left, right in chunks
        ],
        "chunk_count": len(chunks),
        "max_chunk_days": 90,
    }


def plan_chunks(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + MAX_CHUNK, end)
        if nxt <= cursor:
            break
        chunks.append((cursor, nxt))
        cursor = nxt
    for index in range(1, len(chunks)):
        if chunks[index][0] != chunks[index - 1][1] or chunks[index][0] >= chunks[index][1]:
            raise HistoryStoreError("OVERLAPPING_RANGE", "Planned requests overlap or are empty.")
    return chunks


def import_history(
    instrument: str,
    *,
    interval: str,
    start: datetime,
    end: datetime,
    transport: object | None = None,
    caller: object | None = None,
    access_token: str | None = None,
    quarantine: object | None = None,
    retrieved_at: datetime | None = None,
) -> dict:
    """Validate the range, then send one read-only request per planned chunk.

    A response is quarantined. Trusted candles stay empty until the timestamp
    role and timezone are documented. `transport` is ignored so an older caller
    cannot redirect the request.
    """
    del transport
    planned = validate_request(instrument, interval, start, end)
    base = _blocked_result(planned, instrument)
    if caller is None or not access_token:
        base["code"] = "NOT_CONFIGURED"
        base["message"] = "Groww credentials are not available. No historical request was sent."
        return base
    from app.market.retrieval import QuarantineStore, quarantine_record, retrieve_chunk

    store = quarantine if quarantine is not None else QuarantineStore(REPO_ROOT / "var" / "history" / "quarantine")
    moment = retrieved_at or datetime.now(timezone.utc)
    chunks = plan_chunks(start, end)
    records = []
    calls = 0
    for left, right in chunks:
        calls += 1
        chunk = retrieve_chunk(caller, access_token, instrument, left, right, retrieved_at=moment)
        if chunk["retrieval"]["http_status"] is not None:
            records.append(store.write(quarantine_record(chunk, instrument=instrument)))
        if chunk["code"] != "CANDLE_BOUNDARY_UNVERIFIED":
            return _retrieval_result(base, chunk, records, calls)
        if calls < len(chunks):
            continue
    return _retrieval_result(base, chunk, records, calls)


def _blocked_result(planned: dict, instrument: str) -> dict:
    return {
        "ok": False,
        "code": BLOCK_CODE,
        "message": BLOCK_MESSAGE,
        "stored": False,
        "forecast_eligible": False,
        "timestamp_semantics": "UNVERIFIED",
        "timezone": "UNVERIFIED",
        "quality_passed": False,
        "network_calls": 0,
        "candles": [],
        "request": planned,
        "provider_symbol": provider_symbol(instrument),
        "retrieval": None,
        "quarantine": [],
        "states": {
            "request_sent": False,
            "raw_response_retrieved": False,
            "quality_passed": False,
            "timestamp_semantics_verified": False,
            "forecast_eligible": False,
        },
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "ingestion_operational": False,
    }


def _retrieval_result(base: dict, chunk: dict, records: list[dict], calls: int) -> dict:
    numeric_pass = chunk["numeric_quality"] == "PASS"
    base.update(
        {
            "code": chunk["code"],
            "message": chunk["message"],
            "network_calls": calls,
            "quality_passed": numeric_pass,
            "retrieval": chunk["retrieval"],
            "quarantine": [
                {
                    "quarantine_id": item["quarantine_id"],
                    "checksum": item["checksum"],
                    "label": item["label"],
                    "raw_body_sha256": item["raw_body_sha256"],
                    "candle_count": item["candle_count"],
                    "first_raw_timestamp": item["first_raw_timestamp"],
                    "last_raw_timestamp": item["last_raw_timestamp"],
                    "response_start_time": item["response_start_time"],
                    "response_end_time": item["response_end_time"],
                }
                for item in records
            ],
            "states": {
                "request_sent": calls > 0,
                "raw_response_retrieved": bool(records),
                "quality_passed": numeric_pass,
                "timestamp_semantics_verified": False,
                "forecast_eligible": False,
            },
        }
    )
    return base


def parse_groww_candle_payload(payload: object, *, instrument: str) -> dict:
    """Check the documented array shape. Never emits candles.

    Naive timestamps are ambiguous. Timezone-aware timestamps are still
    rejected because the page does not define the boundary.
    """
    provider_symbol(instrument)
    candles = _candle_rows(payload)
    if isinstance(candles, dict):
        return candles
    for row in candles:
        if not isinstance(row, list) or len(row) not in {6, 7}:
            return _parse_failure("SCHEMA_MISMATCH", "A documented candle has 6 or 7 fields.")
        timestamp, open_, high, low, close, volume = row[:6]
        if not isinstance(timestamp, str):
            return _parse_failure("SCHEMA_MISMATCH", "The documented candle timestamp is a string.")
        for price in (open_, high, low, close):
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                return _parse_failure("SCHEMA_MISMATCH", "OHLC values must be numbers.")
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int, float))):
            return _parse_failure("SCHEMA_MISMATCH", "Volume must be a number or null.")
        if volume is not None and volume < 0:
            return _parse_failure("INVALID_VOLUME", "A negative volume was rejected. No candle was stored.")
        aware = _offset_present(timestamp)
        if not aware:
            return _parse_failure(
                "AMBIGUOUS_TIMEZONE",
                "The candle timestamp has no timezone. It was not assumed to be Asia/Kolkata.",
            )
    return _parse_failure(BLOCK_CODE, BLOCK_MESSAGE)


def transport_failure(exc: Exception) -> dict:
    message = redact(str(exc) or exc.__class__.__name__)
    text = str(exc).lower()
    if isinstance(exc, TimeoutError):
        code = "PROVIDER_TIMEOUT"
    elif "429" in text or "rate limit" in text:
        code = "RATE_LIMITED"
        message = "The provider reported a rate limit. The read was not retried."
    else:
        code = "PROVIDER_ERROR"
    return {"ok": False, "code": code, "message": message, "retry": False, "candles": []}


def assess_candles(
    candles: list[Candle],
    *,
    instrument: str,
    calendar: ExchangeCalendar | None = None,
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
) -> dict:
    calendar = calendar or fixture_calendar()
    issues: list[dict] = []
    invalid = 0
    duplicates = 0
    seen: set[datetime] = set()
    for candle in candles:
        if candle.instrument_id != instrument or candle.underlying != instrument:
            issues.append(_issue("INCONSISTENT_INSTRUMENT", f"{candle.instrument_id} does not match {instrument}."))
        report = validate_candle(candle)
        if not report.ok:
            invalid += 1
            issues.extend(issue.model_dump(mode="json") for issue in report.issues)
        assessment = calendar.assess(candle.bar_start)
        if assessment.state is CalendarState.NOT_A_SESSION:
            issues.append(_issue("NOT_A_SESSION", assessment.limitation))
        elif assessment.state is CalendarState.LISTED_SESSION and not calendar.in_regular_window(candle.bar_start):
            issues.append(_issue("OUTSIDE_SESSION_WINDOW", "The bar starts outside the configured 09:15-15:30 IST window."))
        instant = candle.bar_end.astimezone(IST)
        if instant in seen:
            duplicates += 1
            issues.append(_issue("DUPLICATE_TIMESTAMP", f"Duplicate bar end {instant.isoformat()}."))
        seen.add(instant)
    ordered_instants = [candle.bar_end.astimezone(IST) for candle in candles]
    if ordered_instants != sorted(ordered_instants):
        issues.append(_issue("OUT_OF_ORDER", "Candles are not in bar-end order and were not reordered."))
    ordered = sorted(candles, key=lambda item: item.bar_end.astimezone(IST))
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.bar_start.astimezone(IST) < later.bar_end.astimezone(IST) and later.bar_start.astimezone(IST) < earlier.bar_end.astimezone(IST):
            issues.append(_issue("OVERLAPPING_RANGE", "Two candle intervals overlap."))
            break
    gap_counts = {"PROVIDER_OMISSION": 0, "EXPECTED_NON_TRADING": 0, "UNKNOWN": 0, "CONFIRMED_SESSION_GAP": 0}
    unknown_sessions = 0
    if ordered and not duplicates:
        present = {item.bar_end.astimezone(IST) for item in ordered}
        cursor = ordered[0].bar_end.astimezone(IST)
        last = ordered[-1].bar_end.astimezone(IST)
        while cursor < last:
            cursor = cursor + INTERVAL
            if cursor in present or cursor > last:
                continue
            kind = _gap_kind(cursor - INTERVAL, calendar)
            gap_counts[kind] += 1
            if kind == "PROVIDER_OMISSION":
                gap_counts["CONFIRMED_SESSION_GAP"] += 1
            issues.append(_issue(kind, f"Missing 15-minute bar ending {cursor.isoformat()}."))
    for candle in ordered:
        if calendar.assess(candle.bar_start).state is CalendarState.UNKNOWN:
            unknown_sessions += 1
            issues.append(_issue("UNKNOWN_SESSION", "The calendar cannot say whether this date was a session."))
    fatal = [item for item in issues if item["code"] != "UNKNOWN_SESSION"]
    reasons = {item["code"] for item in fatal}
    if unknown_sessions:
        reasons.add("UNKNOWN_SESSION")
    status = "PASS" if not reasons else "REJECTED"
    retrieved = [candle.retrieved_at.astimezone(IST) for candle in candles]
    bounds = [candle.bar_end.astimezone(IST) for candle in ordered]
    return {
        "requested_start": None if requested_start is None else requested_start.astimezone(IST).isoformat(),
        "requested_end": None if requested_end is None else requested_end.astimezone(IST).isoformat(),
        "retrieved_start": None if not bounds else ordered[0].bar_start.astimezone(IST).isoformat(),
        "retrieved_end": None if not bounds else bounds[-1].isoformat(),
        "candle_count": len(candles),
        "duplicate_count": duplicates,
        "invalid_candle_count": invalid,
        "missing_interval_count": (
            gap_counts["PROVIDER_OMISSION"] + gap_counts["EXPECTED_NON_TRADING"] + gap_counts["UNKNOWN"]
        ),
        "unknown_session_count": unknown_sessions,
        "gap_counts": gap_counts,
        "validation_status": status,
        "rejection_reasons": sorted(reasons),
        "issues": issues,
        "calendar_authoritative": False,
        "retrieval_timestamps": sorted({item.isoformat() for item in retrieved}),
    }


def store_source_candles(
    candles: list[Candle],
    *,
    instrument: str,
    store: "HistoryStore",
    calendar: ExchangeCalendar | None = None,
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
    boundary_role: str = "end",
) -> dict:
    if not candles:
        raise HistoryStoreError("NO_CANDLES", "No candles were supplied.")
    if boundary_role not in {"end", "unverified"}:
        raise HistoryStoreError("CANDLE_BOUNDARY_UNVERIFIED", "An unsupported candle-boundary role was rejected.")
    origins = {candle.origin for candle in candles}
    if len(origins) != 1:
        raise HistoryStoreError("MIXED_PROVENANCE", "Candles with different origins cannot be stored together.")
    report = assess_candles(
        candles,
        instrument=instrument,
        calendar=calendar,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    origin = next(iter(origins))
    eligible = (
        report["validation_status"] == "PASS"
        and boundary_role == "end"
        and origin in {DataOrigin.SYNTHETIC, DataOrigin.DOCUMENTED_SAMPLE}
        and report["unknown_session_count"] == 0
    )
    calendar = calendar or fixture_calendar()
    mapping = DOCUMENTED_SYMBOLS.get(instrument)
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": "source_candles",
        "instrument": instrument,
        "provider": "fixture" if origin is not DataOrigin.PROVIDER else "groww",
        "provider_symbol": None if mapping is None else mapping["groww_symbol"],
        "interval": "M15",
        "requested_start": report["requested_start"],
        "requested_end": report["requested_end"],
        "retrieved_start": report["retrieved_start"],
        "retrieved_end": report["retrieved_end"],
        "origin": origin.value,
        "source_verification": "NOT_A_PROVIDER_RETRIEVAL",
        "market_data_verification": False,
        "verification_established": False,
        "point_in_time_revisions_available": False,
        "candle_boundary_role": boundary_role,
        "candle_completion_rule": "retrieved_at_at_or_after_bar_end" if boundary_role == "end" else "unverified",
        "timezone": "Asia/Kolkata",
        "created_at": max(candle.retrieved_at for candle in candles).astimezone(IST).isoformat(),
        "candle_count": len(candles),
        "validation": report,
        "calendar_version": _calendar_version(calendar),
        "calendar_authoritative": False,
        "calendar_listed_sessions": sorted(day.isoformat() for day in calendar.listed_sessions),
        "calendar_closed_dates": sorted(day.isoformat() for day in calendar.closed_dates),
        "feature_set_compatibility": "ohlc-1",
        "known_limitations": [
            "The fixture calendar is not an NSE or BSE holiday calendar.",
            "Provider candle revisions are not available.",
            "A passing OHLC check is not market-data verification.",
        ],
        "forecast_eligible": eligible,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "candles": [candle.model_dump(mode="json") for candle in candles],
    }
    artifact = seal(body)
    store.write(artifact)
    return artifact


def features_from_source(artifact: dict, *, feature_store: DatasetStore | None = None) -> dict:
    from app.market.provenance import quarantine_training_block

    blocked = quarantine_training_block(artifact)
    if blocked is not None:
        return _service_failure(blocked[0], blocked[1])
    if artifact.get("real_market_data_verified") is True:
        return _service_failure("VERIFICATION_REFUSED", "A source dataset cannot claim verified market history.")
    if artifact.get("kind") != "source_candles":
        return _service_failure("LINEAGE_MISSING", "Feature generation requires a sealed source-candle dataset.")
    if not _source_checksum(artifact):
        return _service_failure("CHECKSUM_MISMATCH", "The source dataset checksum does not match its contents.")
    if not _recomputed_research_eligible(artifact):
        return _service_failure(
            "DATASET_REJECTED",
            "The source dataset failed quality or calendar checks and was not sent to the feature pipeline.",
        )
    candles = [Candle.model_validate(row) for row in artifact["candles"]]
    calendar = ExchangeCalendar(
        listed_sessions={date.fromisoformat(day) for day in artifact["calendar_listed_sessions"]},
        closed_dates={date.fromisoformat(day) for day in artifact["calendar_closed_dates"]},
    )
    result = build_dataset(
        candles,
        calendar,
        history_dataset_id=artifact["dataset_id"],
        history_checksum=artifact["checksum"],
    )
    if result.ok and result.artifact is not None and feature_store is not None:
        feature_store.write(result.artifact)
    return {"ok": result.ok, "code": result.code, "message": result.message, "artifact": result.artifact}


def history_store() -> "HistoryStore":
    return HistoryStore(REPO_ROOT / "var" / "history")


class HistoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(self, artifact: dict) -> None:
        if _UNSAFE.intersection(artifact):
            raise HistoryStoreError("UNSAFE_PATH", "A source dataset cannot name a file path.")
        dataset_id = artifact.get("dataset_id")
        if not isinstance(dataset_id, str) or _ID.fullmatch(dataset_id) is None:
            raise HistoryStoreError("INVALID_DATASET_ID", "Dataset id is not a content hash.")
        self._verify(artifact)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(dataset_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def read(self, dataset_id: str) -> dict:
        if _ID.fullmatch(dataset_id) is None:
            raise HistoryStoreError("INVALID_DATASET_ID", "Dataset id is not a content hash.")
        path = self._path(dataset_id)
        if not path.is_file():
            raise HistoryStoreError("NOT_FOUND", "Historical dataset was not found.")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self._verify(artifact)
        if artifact.get("dataset_id") != dataset_id:
            raise HistoryStoreError("CHECKSUM_MISMATCH", "Artifact id does not match the requested id.")
        return artifact

    def list_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(path.stem for path in self.root.glob("*.json") if _ID.fullmatch(path.stem))

    def _path(self, dataset_id: str) -> Path:
        path = (self.root / f"{dataset_id}.json").resolve()
        if path.parent != self.root:
            raise HistoryStoreError("UNSAFE_PATH", "The dataset file would leave the store root.")
        return path

    def _verify(self, artifact: dict) -> None:
        body = {key: value for key, value in artifact.items() if key not in {"dataset_id", "checksum"}}
        digest = content_hash(body)
        if artifact.get("checksum") != digest or artifact.get("dataset_id") != digest:
            raise HistoryStoreError("CHECKSUM_MISMATCH", "Dataset checksum does not match its contents.")
        for key in ("forecast_ready", "paper_approved", "live_approved", "real_market_data_verified"):
            if artifact.get(key) is not False:
                raise HistoryStoreError("VERIFICATION_REFUSED", "A source dataset cannot carry an approval flag.")


def _calendar_version(calendar: ExchangeCalendar) -> str:
    if calendar.listed_sessions == {FIXTURE_DAY} and calendar.closed_dates == {CLOSED_TEST_DAY}:
        return "fixture-m1"
    return "custom-non-authoritative"


def _gap_kind(bar_start: datetime, calendar: ExchangeCalendar) -> str:
    assessment = calendar.assess(bar_start)
    if assessment.state is CalendarState.UNKNOWN:
        return "UNKNOWN"
    if assessment.state is CalendarState.NOT_A_SESSION:
        return "EXPECTED_NON_TRADING"
    if calendar.in_regular_window(bar_start):
        return "PROVIDER_OMISSION"
    return "EXPECTED_NON_TRADING"


def _issue(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _candle_rows(payload: object) -> list | dict:
    if not isinstance(payload, dict):
        return _parse_failure("SCHEMA_MISMATCH", "The candle payload must be an object.")
    if isinstance(payload.get("candles"), list):
        return payload["candles"]
    inner = payload.get("payload")
    if isinstance(inner, dict) and isinstance(inner.get("candles"), list):
        return inner["candles"]
    return _parse_failure("SCHEMA_MISMATCH", "The documented payload has no candles array.")


def _offset_present(timestamp: str) -> bool:
    if timestamp.endswith("Z"):
        return True
    if len(timestamp) >= 6 and timestamp[-6] in {"+", "-"} and timestamp[-3] == ":":
        return True
    return False


def _parse_failure(code: str, message: str) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "candles": [],
        "real_market_data_verified": False,
    }


def _source_checksum(artifact: dict) -> bool:
    body = {key: value for key, value in artifact.items() if key not in {"dataset_id", "checksum"}}
    digest = content_hash(body)
    return artifact.get("dataset_id") == digest and artifact.get("checksum") == digest


def _recomputed_research_eligible(artifact: dict) -> bool:
    """Eligibility comes from the sealed source fields, not from forecast_eligible."""
    validation = artifact.get("validation") if isinstance(artifact.get("validation"), dict) else {}
    return (
        validation.get("validation_status") == "PASS"
        and artifact.get("candle_boundary_role") == "end"
        and artifact.get("origin") in {"SYNTHETIC", "DOCUMENTED_SAMPLE"}
        and validation.get("unknown_session_count") == 0
        and artifact.get("real_market_data_verified") is False
    )


def _service_failure(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message, "artifact": None}
