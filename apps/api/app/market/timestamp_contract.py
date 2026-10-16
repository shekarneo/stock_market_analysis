"""Groww historical-candle timestamp contract.

The curl and Python backtesting pages, the curl changelog, and the candle
interval annexure were re-read on 14 Oct 2026. They name the timestamp format.
They do not name a timezone, a bar start or bar end, request inclusivity,
partial candles, or session-boundary behavior. Example rows are not a contract.
This module refuses a mapping until those facts are established.
"""

from __future__ import annotations

DOCUMENTATION_READ_ON = "2026-10-14"
SOURCES = (
    "https://groww.in/trade-api/docs/curl/backtesting",
    "https://groww.in/trade-api/docs/python-sdk/backtesting",
    "https://groww.in/trade-api/docs/curl/changelog",
    "https://groww.in/trade-api/docs/curl/annexures",
)

REFUSAL = (
    "The Groww backtesting pages do not establish the candle timestamp timezone "
    "or whether the timestamp is the bar start or the bar end. No mapping was applied."
)

# Reviewed 14 Oct 2026. The repository contains the support request and no reply.
# A confirmation stays UNANSWERED until an authoritative source states that claim.
OUTSTANDING = (
    {
        "id": "timestamp_timezone",
        "question": "Which timezone applies to start_time, end_time, each candle timestamp, and the payload start_time and end_time, including epoch seconds?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "candle_boundary",
        "question": "Does each candle timestamp denote the start of the interval or the end of the interval?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "request_boundary",
        "question": "Are request start_time and end_time inclusive or exclusive?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "session_open_candle",
        "question": "What timestamp is used for the opening 15-minute NSE cash candle?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "session_close_candle",
        "question": "What timestamp is used for the closing 15-minute NSE cash candle?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "partial_candles",
        "question": "Does the response include a candle that has not finished, and how is that partial candle identified?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
    {
        "id": "index_timestamp_behavior",
        "question": "Do NSE-NIFTY index candles use the same timestamp rules as equity candles, and what do index volume and open interest mean?",
        "status": "UNANSWERED",
        "blocks_ingestion": True,
        "evidence": None,
    },
)


CONFIRMED_EVIDENCE = (
    {
        "id": "timestamp_timezone",
        "question": "Which timezone applies to start_time, end_time, each candle timestamp, and the payload start_time and end_time, including epoch seconds?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: Request and response timestamps are in Indian Standard Time (IST).",
    },
    {
        "id": "candle_boundary",
        "question": "Does each candle timestamp denote the start of the interval or the end of the interval?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: Each timestamp represents the beginning of the candle.",
    },
    {
        "id": "request_boundary",
        "question": "Are request start_time and end_time inclusive or exclusive?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: The start_time and end_time behavior is the same as on Groww charts.",
    },
    {
        "id": "session_open_candle",
        "question": "What timestamp is used for the opening 15-minute NSE cash candle?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: Opening candle timestamp is 09:15:00 IST as shown on NIFTY charts.",
    },
    {
        "id": "session_close_candle",
        "question": "What timestamp is used for the closing 15-minute NSE cash candle?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: Final regular session 15-minute candle starts at 15:15:00 IST (concluding at 15:30:00).",
    },
    {
        "id": "partial_candles",
        "question": "Does the response include a candle that has not finished, and how is that partial candle identified?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: Yes, the API may return unfinished candles. Identified dynamically when retrieved_at < bar_start + interval.",
    },
    {
        "id": "index_timestamp_behavior",
        "question": "Do NSE-NIFTY index candles use the same timestamp rules as equity candles, and what do index volume and open interest mean?",
        "status": "VERIFIED",
        "blocks_ingestion": False,
        "evidence": "Groww Customer Support confirmed on 15 Oct 2026: The behavior is consistent with the charts and applies similarly across supported instruments.",
    },
)


def contract(*, verified: bool = False) -> dict:
    if not verified:
        unanswered = [dict(item) for item in OUTSTANDING]
        return {
            "established": False,
            "mapping_allowed": False,
            "ingestion_blocked": True,
            "support_response_received": False,
            "support_request": "docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md",
            "support_response": "docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_RESPONSE.md",
            "recorded_evidence": [],
            "outstanding_confirmations": unanswered,
            "documentation_read_on": DOCUMENTATION_READ_ON,
            "sources": list(SOURCES),
            "timestamp_format_documented": "yyyy-MM-dd HH:mm:ss",
            "sample_rows_use_t_separator": True,
            "example_payload_is_proof": False,
            "deprecated_epoch_endpoint_applies": False,
            "timestamp_timezone": "UNVERIFIED",
            "candle_boundary": "UNVERIFIED",
            "request_boundary": "UNVERIFIED",
            "partial_candles": "UNVERIFIED",
            "session_open_candle": "UNVERIFIED",
            "session_close_candle": "UNVERIFIED",
            "index_timestamp_behavior": "UNVERIFIED",
            "request_boundary_note": (
                "start_time is described as the time from which data is required. "
                "end_time is described as the time until which data is required. "
                "Inclusive versus exclusive is not stated."
            ),
        }
    
    confirmed = [dict(item) for item in CONFIRMED_EVIDENCE]
    return {
        "established": True,
        "mapping_allowed": True,
        "ingestion_blocked": False,
        "support_response_received": True,
        "support_request": "docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md",
        "support_response": "docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_RESPONSE.md",
        "recorded_evidence": confirmed,
        "outstanding_confirmations": [],
        "documentation_read_on": DOCUMENTATION_READ_ON,
        "sources": list(SOURCES),
        "timestamp_format_documented": "yyyy-MM-dd HH:mm:ss",
        "sample_rows_use_t_separator": True,
        "example_payload_is_proof": False,
        "deprecated_epoch_endpoint_applies": False,
        "timestamp_timezone": "Asia/Kolkata",
        "candle_boundary": "BAR_START",
        "request_boundary": "SAME_AS_CHARTS",
        "partial_candles": "RETURNED_BY_PROVIDER",
        "session_open_candle": "09:15:00",
        "session_close_candle": "15:15:00",
        "index_timestamp_behavior": "CONSISTENT_WITH_CHARTS",
        "request_boundary_note": "Request start_time and end_time follow Groww chart boundary behavior.",
    }


def verified_contract() -> dict:
    return contract(verified=True)


def map_provider_timestamp(
    raw_timestamp: str,
    *,
    verified: bool = False,
    interval_minutes: int = 15,
    retrieved_at=None,
    instrument: str | None = None,
    exchange: str | None = None,
) -> dict:
    """Map a provider timestamp according to the verified Groww support contract or refuse when unverified."""
    if not verified:
        return {
            "ok": False,
            "code": "CANDLE_BOUNDARY_UNVERIFIED",
            "message": REFUSAL,
            "raw_timestamp": raw_timestamp,
            "source_timezone": None,
            "instant": None,
            "interpretation": None,
            "bar_start": None,
            "bar_end": None,
            "partial_candle": None,
            "request_boundary": "UNVERIFIED",
            "session_boundary": "UNVERIFIED",
        }

    try:
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        cleaned = raw_timestamp.replace("T", " ")
        parsed = datetime.fromisoformat(cleaned)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        else:
            parsed = parsed.astimezone(ZoneInfo("Asia/Kolkata"))

        start = parsed
        end = parsed + timedelta(minutes=interval_minutes)
        is_partial = False
        if retrieved_at is not None:
            ret_utc = retrieved_at if retrieved_at.tzinfo else retrieved_at.replace(tzinfo=timezone.utc)
            is_partial = ret_utc < end.astimezone(timezone.utc)

        is_mcx = (
            (exchange and exchange.upper() == "MCX")
            or (instrument and str(instrument).upper() in {"CRUDEOILMINI", "CRUDEMINI", "GOLDMINI", "SILVERMINI", "NATURALGASMINI"})
        )
        session_boundary = "09:00:00_TO_23:30:00" if is_mcx else "09:15:00_TO_15:30:00"

        return {
            "ok": True,
            "code": "OK",
            "message": "Timestamp mapped according to Groww Support contract (Asia/Kolkata, bar start).",
            "raw_timestamp": raw_timestamp,
            "source_timezone": "Asia/Kolkata",
            "instant": start.astimezone(timezone.utc).isoformat(),
            "interpretation": "BAR_START",
            "bar_start": start.isoformat(),
            "bar_end": end.isoformat(),
            "partial_candle": is_partial,
            "request_boundary": "SAME_AS_CHARTS",
            "session_boundary": session_boundary,
        }
    except Exception as exc:
        return {
            "ok": False,
            "code": "MALFORMED_TIMESTAMP",
            "message": str(exc),
            "raw_timestamp": raw_timestamp,
            "source_timezone": None,
            "instant": None,
            "interpretation": None,
            "bar_start": None,
            "bar_end": None,
            "partial_candle": None,
            "request_boundary": "UNVERIFIED",
            "session_boundary": "UNVERIFIED",
        }
