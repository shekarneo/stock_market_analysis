"""Read-only checks for a quarantined Groww payload.

A passing structural check does not establish a timezone or a candle boundary,
and it does not create a trusted dataset. This module never writes a file.
"""

from __future__ import annotations

from datetime import datetime

from app.features.pipeline import content_hash

MINIMUM_TRUSTED_EVIDENCE = (
    "A written provider statement naming the timezone of NSE-NIFTY 15-minute candle timestamps.",
    "A written provider statement that each timestamp is the bar start or the bar end.",
    "A written provider statement of whether start_time and end_time are inclusive.",
    "A written provider statement identifying the session-open and session-close candle for NSE-NIFTY 15-minute cash index data.",
    "A written provider statement of how a partial 15-minute candle is identified.",
)


def validate_quarantine_payload(record: dict, siblings: list[dict] | None = None) -> dict:
    """Classify what the stored payload can prove. Does not modify the record."""
    checks: list[dict] = []
    checks.append(_checksum(record))
    checks.append(_raw_http_body(record))
    candles = record.get("raw_candles")
    stored = candles if isinstance(candles, list) else None
    checks.append(_stored_count(record, stored))
    timestamps = _timestamps(stored)
    checks.extend(_timestamp_checks(record, timestamps))
    checks.extend(_price_checks(stored))
    checks.append(_expected_count())
    checks.append(_session_boundaries())
    checks.append(_request_semantics())
    checks.append(_sibling_match(record, siblings or []))
    return _group(checks)


def _checksum(record: dict) -> dict:
    if "checksum" not in record or "quarantine_id" not in record:
        return _item("FAIL", "checksum", "The record has no checksum.")
    body = {key: value for key, value in record.items() if key not in {"quarantine_id", "checksum"}}
    digest = content_hash(body)
    if record.get("checksum") == digest and record.get("quarantine_id") == digest:
        return _item("PASS", "checksum", "The record checksum matches its stored contents.")
    return _item("FAIL", "checksum", "The record checksum does not match its stored contents.")


def _raw_http_body(record: dict) -> dict:
    recorded = record.get("raw_body_sha256")
    if not isinstance(recorded, str) or len(recorded) != 64:
        return _item("FAIL", "raw_http_body", "The record does not cite a SHA-256 for the provider body.")
    return _item(
        "UNDETERMINED",
        "raw_http_body",
        "The provider body bytes are not stored, so the cited SHA-256 cannot be recomputed.",
    )


def _stored_count(record: dict, stored: list | None) -> dict:
    claimed = record.get("candle_count")
    if stored is None:
        return _item("UNDETERMINED", "stored_candle_count", "This record does not store the candle array.")
    if claimed == len(stored):
        return _item("PASS", "stored_candle_count", f"The stored array length is {len(stored)}.")
    return _item("FAIL", "stored_candle_count", "The stored array length differs from candle_count.")


def _timestamps(stored: list | None) -> list[str] | None:
    if stored is None:
        return None
    return [row[0] for row in stored if isinstance(row, list) and row and isinstance(row[0], str)]


def _timestamp_checks(record: dict, timestamps: list[str] | None) -> list[dict]:
    observed = timestamps
    if observed is None:
        observed = [item for item in (record.get("first_raw_timestamp"), record.get("last_raw_timestamp")) if isinstance(item, str)]
    spacing_name = _spacing_name(record.get("candle_interval"))
    if not observed:
        return [
            _item("UNDETERMINED", name, "No timestamp text is stored in this record.")
            for name in ("timestamp_parse", "timestamp_order", "duplicate_timestamps", spacing_name, "timezone_offset", "timezone_identity", "requested_endpoints")
        ]
    parsed: list[datetime] = []
    for item in observed if timestamps is not None else observed:
        try:
            parsed.append(datetime.fromisoformat(item))
        except ValueError:
            return [
                _item("FAIL", "timestamp_parse", "A stored timestamp is not ISO-8601 text."),
                _item("UNDETERMINED", "timestamp_order", "Order was not judged because parsing failed."),
                _item("UNDETERMINED", "duplicate_timestamps", "Duplicates were not judged because parsing failed."),
                _item("UNDETERMINED", spacing_name, "Spacing was not judged because parsing failed."),
                _item("UNDETERMINED", "timezone_offset", "An offset was not judged because parsing failed."),
                _item("UNDETERMINED", "timezone_identity", "The provider timezone is not documented."),
                _endpoint_check(record, timestamps),
            ]
    checks = [_item("PASS", "timestamp_parse", "Every stored timestamp parses as ISO-8601 text.")]
    if timestamps is None:
        checks.extend(
            [
                _item("UNDETERMINED", "timestamp_order", "The full timestamp list is not stored."),
                _item("UNDETERMINED", "duplicate_timestamps", "The full timestamp list is not stored."),
                _item("UNDETERMINED", spacing_name, "The full timestamp list is not stored."),
            ]
        )
    else:
        checks.append(
            _item("PASS", "timestamp_order", "Timestamps are in ascending text order.")
            if timestamps == sorted(timestamps)
            else _item("FAIL", "timestamp_order", "Timestamps are not in ascending order. They were not reordered.")
        )
        checks.append(
            _item("PASS", "duplicate_timestamps", "No timestamp text is repeated.")
            if len(timestamps) == len(set(timestamps))
            else _item("FAIL", "duplicate_timestamps", "A timestamp text is repeated.")
        )
        checks.append(_spacing(parsed, record.get("candle_interval")))
    aware = [item.tzinfo is not None for item in parsed]
    if any(aware) and not all(aware):
        checks.append(_item("FAIL", "timezone_offset", "The stored timestamps mix offset-less and offset-bearing text."))
    elif all(aware):
        checks.append(_item("PASS", "timezone_offset", "Every stored timestamp includes an offset. The offset is not a verified provider contract."))
    else:
        checks.append(_item("PASS", "timezone_offset", "Every stored timestamp is offset-less."))
    checks.append(_item("UNDETERMINED", "timezone_identity", "No stored provider statement names the timestamp timezone."))
    checks.append(_endpoint_check(record, timestamps if timestamps is not None else observed))
    return checks


def _spacing_name(interval: object) -> str:
    return "spacing_1_minute" if interval == "1minute" else "spacing_15_minutes"


def _spacing(parsed: list[datetime], interval: object = None) -> dict:
    name = _spacing_name(interval)
    if len(parsed) < 2:
        return _item("UNDETERMINED", name, "Fewer than two timestamps are stored.")
    if any(item.tzinfo is not None for item in parsed) and any(item.tzinfo is None for item in parsed):
        return _item("UNDETERMINED", name, "Mixed offsets were not subtracted.")
    deltas = [(parsed[index] - parsed[index - 1]).total_seconds() for index in range(1, len(parsed))]
    if interval == "1minute":
        if any(delta <= 0 for delta in deltas):
            return _item("FAIL", name, "A consecutive pair is not later than the previous timestamp.")
        gaps = sorted({delta for delta in deltas if delta != 60.0})
        if not gaps:
            return _item(
                "PASS",
                name,
                "Consecutive parsed timestamps are 60 seconds apart. Spacing does not identify bar start or bar end, and it does not prove that no minute is missing outside this list.",
            )
        shown = ", ".join(str(int(delta)) for delta in gaps)
        return _item(
            "UNDETERMINED",
            name,
            f"Positive gaps other than 60 seconds were observed: {shown}. They are not classified as a market break or as missing minutes.",
        )
    if set(deltas) == {900.0}:
        return _item(
            "PASS",
            name,
            "Consecutive parsed timestamps are 900 seconds apart. Spacing does not identify bar start or bar end.",
        )
    return _item("FAIL", name, "Consecutive parsed timestamps are not 900 seconds apart.")


def _endpoint_check(record: dict, timestamps: list[str] | None) -> dict:
    start = _normalise_request(record.get("requested_start_sent"))
    end = _normalise_request(record.get("requested_end_sent"))
    if timestamps is None or start is None or end is None:
        return _item("UNDETERMINED", "requested_endpoints", "The request bounds or timestamp list is not stored.")
    if timestamps[0] == start and timestamps[-1] == end:
        return _item(
            "PASS",
            "requested_endpoints",
            "The first and last timestamp texts match the requested bounds after the space is written as T. Inclusivity remains unverified.",
        )
    return _item("FAIL", "requested_endpoints", "The first or last timestamp text differs from the requested bounds.")


def _price_checks(stored: list | None) -> list[dict]:
    if stored is None:
        return [
            _item("UNDETERMINED", name, "The candle array is not stored in this record.")
            for name in ("ohlc", "volume", "open_interest")
        ]
    if not stored:
        return [
            _item("UNDETERMINED", name, "The candle array is empty.")
            for name in ("ohlc", "volume", "open_interest")
        ]
    for row in stored:
        if not isinstance(row, list) or len(row) not in {6, 7}:
            return [
                _item("FAIL", "ohlc", "A candle does not have 6 or 7 fields."),
                _item("UNDETERMINED", "volume", "Volume was not judged."),
                _item("UNDETERMINED", "open_interest", "Open interest was not judged."),
            ]
        prices = row[1:5]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in prices):
            return [
                _item("FAIL", "ohlc", "An OHLC field is not a number."),
                _item("UNDETERMINED", "volume", "Volume was not judged."),
                _item("UNDETERMINED", "open_interest", "Open interest was not judged."),
            ]
        open_, high, low, close = (float(value) for value in prices)
        if high < max(open_, close) or low > min(open_, close) or high < low:
            return [
                _item("FAIL", "ohlc", "High and low do not contain open and close."),
                _item("UNDETERMINED", "volume", "Volume was not judged after an OHLC failure."),
                _item("UNDETERMINED", "open_interest", "Open interest was not judged after an OHLC failure."),
            ]
        volume = row[5]
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, (int, float)) or float(volume) < 0):
            return [
                _item("PASS", "ohlc", "OHLC values are numeric and internally consistent."),
                _item("FAIL", "volume", "Volume is not null or a non-negative number."),
                _item("UNDETERMINED", "open_interest", "Open interest was not judged after a volume failure."),
            ]
        if len(row) == 7:
            interest = row[6]
            if interest is not None and (isinstance(interest, bool) or not isinstance(interest, (int, float)) or float(interest) < 0):
                return [
                    _item("PASS", "ohlc", "OHLC values are numeric and internally consistent."),
                    _item("PASS", "volume", "Volume is null or a non-negative number."),
                    _item("FAIL", "open_interest", "Open interest is not null or a non-negative number."),
                ]
    return [
        _item("PASS", "ohlc", "OHLC values are numeric and internally consistent."),
        _item("PASS", "volume", "Volume is null or a non-negative number. Null was not changed to zero."),
        _item("PASS", "open_interest", "Open interest is absent, null, or a non-negative number."),
    ]


def _expected_count() -> dict:
    return _item(
        "UNDETERMINED",
        "expected_observation_count",
        "The documented request does not say whether the bounds are inclusive, so the expected candle count cannot be calculated.",
    )


def _session_boundaries() -> dict:
    return _item(
        "UNDETERMINED",
        "session_boundaries",
        "No stored statement identifies the opening candle, the closing candle, or a partial candle.",
    )


def _request_semantics() -> dict:
    return _item(
        "UNDETERMINED",
        "request_boundary_semantics",
        "Matching endpoint text does not establish inclusive or exclusive request bounds.",
    )


def _sibling_match(record: dict, siblings: list[dict]) -> dict:
    body_hash = record.get("raw_body_sha256")
    related = [item for item in siblings if item.get("raw_body_sha256") == body_hash and item.get("quarantine_id") != record.get("quarantine_id")]
    if not related:
        return _item("UNDETERMINED", "raw_summary_match", "No second record cites the same provider-body SHA-256.")
    for other in related:
        left = record.get("raw_candles")
        right = other.get("raw_candles")
        if left != right:
            return _item(
                "FAIL",
                "raw_summary_match",
                "Records citing the same provider-body SHA-256 do not store the same candle array. Neither record was changed.",
            )
        for field in ("candle_count", "first_raw_timestamp", "last_raw_timestamp"):
            if record.get(field) != other.get(field):
                return _item("FAIL", "raw_summary_match", f"The paired records differ in {field}. Neither record was changed.")
    return _item("PASS", "raw_summary_match", "The paired records store the same candle array and summary fields.")


def _normalise_request(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.replace(" ", "T")


def _item(status: str, identifier: str, detail: str) -> dict:
    return {"status": status, "id": identifier, "detail": detail}


def ingestion_diagnostic(record: dict, validation: dict | None = None) -> dict:
    """Describe one stored response. Does not write the record or infer a timezone."""
    validation = validation if validation is not None else validate_quarantine_payload(record)
    candles = record.get("raw_candles") if isinstance(record.get("raw_candles"), list) else []
    structural_ids = {
        "checksum",
        "stored_candle_count",
        "timestamp_parse",
        "timestamp_order",
        "duplicate_timestamps",
        "spacing_1_minute",
        "spacing_15_minutes",
        "timezone_offset",
        "ohlc",
        "volume",
        "open_interest",
    }
    structural = [
        item
        for item in validation["passed"] + validation["failed"] + validation["undetermined"]
        if item["id"] in structural_ids
    ]
    if any(item["status"] == "FAIL" for item in structural):
        structural_status = "FAIL"
    elif structural and all(item["status"] == "PASS" for item in structural):
        structural_status = "PASS"
    else:
        structural_status = "UNDETERMINED"
    return {
        "provider": record.get("provider") or "groww",
        "endpoint": "GET /v1/historical/candles",
        "instrument": record.get("groww_symbol") or record.get("instrument"),
        "interval": record.get("candle_interval") or record.get("interval"),
        "requested_start": record.get("requested_start_sent"),
        "requested_end": record.get("requested_end_sent"),
        "http_status": record.get("http_status"),
        "provider_status": record.get("provider_status"),
        "candle_count": record.get("candle_count") if record.get("candle_count") is not None else len(candles),
        "timestamp_format_observed": _timestamp_format(candles),
        "observed_spacing_seconds": _observed_spacing(candles),
        "structural_validation": structural_status,
        "structural_checks": structural,
        "provider_contract_verified": False,
        "timestamp_semantics_verified": False,
        "session_semantics_verified": False,
        "quarantine_reason": (
            "The provider contract does not establish timestamp timezone, bar start versus bar end, "
            "request inclusivity, session candles, or incomplete candles."
        ),
        "label": record.get("label") or "UNVERIFIED_PROVIDER",
        "validation": {
            "passed": [item["id"] for item in validation["passed"]],
            "failed": [item["id"] for item in validation["failed"]],
            "undetermined": [item["id"] for item in validation["undetermined"]],
        },
        "trusted_dataset_created": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }


def _timestamp_format(candles: list) -> str:
    stamps = [row[0] for row in candles if isinstance(row, list) and row and isinstance(row[0], str)]
    if not stamps:
        return "NOT_STORED"
    try:
        parsed = [datetime.fromisoformat(item) for item in stamps]
    except ValueError:
        return "UNPARSEABLE"
    if any(item.tzinfo is not None for item in parsed):
        return "ISO-8601 with an offset. The offset is not a verified provider timezone."
    return "offset-less ISO-8601 text"


def _observed_spacing(candles: list) -> float | None:
    stamps = [row[0] for row in candles if isinstance(row, list) and row and isinstance(row[0], str)]
    if len(stamps) < 2:
        return None
    try:
        parsed = [datetime.fromisoformat(item) for item in stamps]
    except ValueError:
        return None
    if any(item.tzinfo is not None for item in parsed) and any(item.tzinfo is None for item in parsed):
        return None
    deltas = {(parsed[index] - parsed[index - 1]).total_seconds() for index in range(1, len(parsed))}
    if len(deltas) == 1:
        return next(iter(deltas))
    return None


def _group(checks: list[dict]) -> dict:
    return {
        "passed": [item for item in checks if item["status"] == "PASS"],
        "failed": [item for item in checks if item["status"] == "FAIL"],
        "undetermined": [item for item in checks if item["status"] == "UNDETERMINED"],
        "trusted_dataset_created": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "minimum_evidence": list(MINIMUM_TRUSTED_EVIDENCE),
    }
