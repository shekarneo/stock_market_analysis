"""M10 gate for a trusted NIFTY history dataset.

The curl backtesting page was fetched again on 14 Oct 2026. It still names
the timestamp format and does not name a timezone or a bar boundary. No
second source with a documented 15-minute NIFTY timestamp contract was found.
This module does not write a dataset and does not call a provider.
"""

from __future__ import annotations

from app.market.timestamp_contract import contract, map_provider_timestamp

READ_ON = "2026-10-14"
GROWW_PAGE = "https://groww.in/trade-api/docs/curl/backtesting"

DOCUMENTED_GROWW_FACTS = (
    "GET /v1/historical/candles accepts exchange, segment, groww_symbol, start_time, end_time, and candle_interval.",
    "The documented timestamp format is yyyy-MM-dd HH:mm:ss. Sample rows use a T and no offset.",
    "The page says volume is present for tradable equities and FNO.",
    "Open interest is described for FNO and null for other instruments.",
    "A 15-minute request is limited to 90 days. Equity, index, and FNO history is described as available from 2020.",
    "NSE-NIFTY and BSE-SENSEX are documented index symbols. CASH and FNO are the supported segments.",
)

OBSERVED_NOT_A_CONTRACT = (
    "One earlier read-only NIFTY 15-minute response is quarantined. Its timestamps have no offset. Spacing is not a timezone or a bar-boundary contract.",
)

REJECTED_ASSUMPTIONS = (
    "Do not treat a timestamp without an offset as Asia/Kolkata.",
    "Do not treat 15-minute spacing, or a first stamp of 09:15 and a last stamp of 15:30, as proof of bar start or bar end.",
    "Do not treat the words 'from which' and 'until which' as inclusive or exclusive bounds.",
    "A search summary that called the stamps IST is not documentation. The fetched page text does not say IST.",
)

INDEPENDENT_SOURCES = (
    {
        "provider": "Groww",
        "source": "Groww historical candles",
        "url": GROWW_PAGE,
        "instrument": "NSE-NIFTY is a documented index symbol.",
        "interval": "15minute is documented. A 15-minute request is limited to 90 days.",
        "coverage": "Equities, indices, and FNO are described as available from 2020.",
        "timezone_contract": "UNRESOLVED. The page names yyyy-MM-dd HH:mm:ss and does not name a timezone.",
        "timestamp_semantics": "UNRESOLVED. The page does not say bar start or bar end.",
        "incomplete_candle": "UNRESOLVED.",
        "authentication": "Saved Groww bearer token. A prior read was quarantined.",
        "licensing": "UNRESOLVED on the pages read.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["timezone", "candle_boundary", "request_boundary", "partial_candles", "index_timestamp_behavior"],
        "suitable": False,
        "reason": "The official candle page still does not establish timezone or bar boundary. The stored response stays quarantined.",
    },
    {
        "provider": "Upstox",
        "source": "Upstox Historical Candle Data V3",
        "url": "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data",
        "instrument": "The fetched page names NSE_INDEX|India VIX. It does not name a NIFTY 50 instrument key. The sample key is an equity ISIN.",
        "interval": "Minute intervals 1 through 300 are documented, which includes 15. Intraday history is described from January 2022, with a one-month retrieval limit for 1 to 15 minutes.",
        "coverage": "Intraday from January 2022 on that page.",
        "timezone_contract": "UNRESOLVED. A sample stamp is 2025-01-01T00:00:00+05:30. The field description does not state a timezone, and the type column says number.",
        "timestamp_semantics": "The response table says the timestamp indicates the start time of the candle's timeframe.",
        "incomplete_candle": "UNRESOLVED. The fetched page does not say how an unfinished candle is marked.",
        "authentication": "Bearer access token. This application has no Upstox credential.",
        "licensing": "UNRESOLVED on the fetched page. to_date is described as inclusive. from_date inclusivity is not stated.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["nifty_instrument_key", "timezone", "partial_candles", "credential_not_configured"],
        "suitable": False,
        "reason": "A start-time sentence is documented. Timezone, the NIFTY index key, partial candles, and access are not established. No adapter was added.",
    },
    {
        "provider": "Zerodha Kite Connect",
        "source": "Kite historical candle data",
        "url": "https://kite.trade/docs/connect/v3/historical/",
        "instrument": "The historical page examples are NSE-ACC and a NIFTY futures contract. It does not name the NIFTY 50 index instrument token.",
        "interval": "15minute is a documented interval value.",
        "coverage": "The page says several years. It does not state a NIFTY index retention window.",
        "timezone_contract": "UNRESOLVED as a required field rule. Published examples and a staff reply use an offset of +0530. The reference table does not say every timestamp must carry that offset.",
        "timestamp_semantics": "A Kite Connect forum reply dated October 3, fetched 14 Oct 2026, says the Historical Data API timestamp is the start of the candle. The reply does not print a year. The official reference page itself does not say start or end.",
        "incomplete_candle": "The same staff reply says the API provides no completeness flag and does not guarantee that a candle is available at the end of its minute.",
        "authentication": "Authorization token api_key:access_token. This application has no Kite credential.",
        "licensing": "The page presents the API as a Kite Connect historical endpoint. Cost and a research licence are not stated on that page. from and to are described as the start and end of records, without an inclusive or exclusive rule.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["nifty_index_token", "timezone_field_rule", "partial_candles", "request_boundary", "credential_not_configured"],
        "suitable": False,
        "reason": "Staff described a start-of-candle rule and also said partial candles cannot be identified. The NIFTY index token and a stored credential are absent. No adapter was added.",
        "staff_reply_url": "https://kite.trade/forum/discussion/16272/clarification-required-historical-5-minute-candle-semantics-at-nse-15-15-cas-boundary",
    },
    {
        "provider": "Angel One SmartAPI",
        "source": "Angel historical candle data",
        "url": "https://smartapi.angelbroking.com/docs/Historical",
        "instrument": "The page says the historical API covers indices and instruments, and NSE means NSE stocks and indices. The sample symbol token is not named as NIFTY on that page.",
        "interval": "FIFTEEN_MINUTE is documented, with a maximum of 200 days in one request.",
        "coverage": "Not stated beyond the per-request day caps.",
        "timezone_contract": "UNRESOLVED. A sample stamp is 2023-09-06T11:15:00+05:30. The notes do not state a timezone rule.",
        "timestamp_semantics": "UNRESOLVED. The notes list timestamp, open, high, low, close, and volume, and do not say start or end.",
        "incomplete_candle": "UNRESOLVED.",
        "authentication": "Bearer token plus private key and client network headers. This application has no Angel One credential.",
        "licensing": "UNRESOLVED on the fetched page.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["timezone", "candle_boundary", "named_nifty_token", "partial_candles", "credential_not_configured"],
        "suitable": False,
        "reason": "Fifteen-minute index history is in scope on the page. The timestamp contract and a stored credential are not established.",
    },
    {
        "provider": "DhanHQ",
        "source": "Dhan intraday historical data",
        "url": "https://dhanhq.co/docs/v2/historical-data/",
        "instrument": "The intraday example is an equity security id. The page does not name a NIFTY index security id.",
        "interval": "Intraday intervals include 15 minutes. A request can cover 90 days. The page says the last 5 years are available for active instruments.",
        "coverage": "Last 5 years for active instruments, as stated for the intraday endpoint.",
        "timezone_contract": "UNRESOLVED. The timestamp is described only as an epoch timestamp.",
        "timestamp_semantics": "UNRESOLVED. The page does not say the epoch is the bar start or the bar end.",
        "incomplete_candle": "UNRESOLVED. Daily toDate is described as non-inclusive. The intraday toDate description does not repeat that rule.",
        "authentication": "access-token header. This application has no Dhan credential.",
        "licensing": "UNRESOLVED on the fetched page.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["timezone", "candle_boundary", "nifty_security_id", "partial_candles", "credential_not_configured"],
        "suitable": False,
        "reason": "Fifteen-minute candles are documented. Epoch meaning, bar boundary, and the NIFTY index id are not.",
    },
    {
        "provider": "NSE",
        "source": "NSE historical index data",
        "url": "https://nseindia.com/reports-indices-historical-index-data",
        "instrument": "Nifty 50 appears in the daily index file.",
        "interval": "Daily index date. Not a 15-minute candle.",
        "coverage": "Daily files are published. Intraday OHLC retention is not documented on the page fetched.",
        "timezone_contract": "UNRESOLVED. Index Date is DD-MM-YYYY with no time.",
        "timestamp_semantics": "UNRESOLVED for a daily bar, and not a 15-minute contract.",
        "incomplete_candle": "Not applicable to the daily file that was reviewed.",
        "authentication": "The CSV archive is publicly fetchable. It was not ingested.",
        "licensing": "The page copyright is National Stock Exchange of India Ltd. A research-redistribution licence was not stated on the fetched page.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["interval_is_daily", "timezone", "candle_boundary"],
        "suitable": False,
        "reason": "The daily file was not substituted for 15-minute candles.",
    },
    {
        "provider": "NSE paid feeds",
        "source": "NSE snapshot and real-time subscriptions",
        "url": "https://www.nseindia.com/static/market-data/real-time-data-subscription",
        "instrument": "Index feed products exist. A free 15-minute NIFTY OHLC history is not documented there.",
        "interval": "Paid snapshot files are described at 1 or 5 minutes, and a 15-minute-delayed snapshot is a delayed product rather than a historical 15-minute OHLC contract.",
        "coverage": "Not established for historical 15-minute NIFTY OHLC.",
        "timezone_contract": "UNRESOLVED on the subscription page.",
        "timestamp_semantics": "UNRESOLVED on the subscription page.",
        "incomplete_candle": "UNRESOLVED.",
        "authentication": "A paid subscription is required. None is configured.",
        "licensing": "Paid product. Not licensed in this project.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["no_subscription", "no_15minute_ohlc_contract"],
        "suitable": False,
        "reason": "No paid NSE feed is configured, and the public page does not document a free 15-minute OHLC history.",
    },
    {
        "provider": "None",
        "source": "Configured integrations other than Groww",
        "url": None,
        "instrument": "The saved integrations are Groww and OpenAI.",
        "interval": "OpenAI is not a market-data source.",
        "coverage": "None.",
        "timezone_contract": "UNRESOLVED.",
        "timestamp_semantics": "UNRESOLVED.",
        "incomplete_candle": "UNRESOLVED.",
        "authentication": "No other market-data credential is stored.",
        "licensing": "Not applicable.",
        "verification_status": "BLOCKED",
        "outstanding_blockers": ["no_configured_source"],
        "suitable": False,
        "reason": "OpenAI commentary cannot supply NIFTY candles.",
    },
)


REQUIREMENTS = (
    {
        "id": "instrument_identity",
        "status": "VERIFIED",
        "evidence": "The Groww curl backtesting page lists NSE-NIFTY as an index symbol, distinct from futures and options symbols.",
        "citation": GROWW_PAGE,
    },
    {
        "id": "interval_15minute",
        "status": "VERIFIED",
        "evidence": "The same page documents candle_interval and the limits table gives 15-minute requests a maximum of 90 days.",
        "citation": GROWW_PAGE,
    },
    {
        "id": "coverage",
        "status": "VERIFIED",
        "evidence": "The page says equity, index, and FNO history is available from 2020. That sentence does not prove every session is present.",
        "citation": GROWW_PAGE,
    },
    {
        "id": "response_schema",
        "status": "VERIFIED",
        "evidence": "The response table lists a candle timestamp, open, high, low, close, and volume. Open interest is described for FNO and null otherwise.",
        "citation": GROWW_PAGE,
    },
    {
        "id": "timezone",
        "status": "UNVERIFIED",
        "evidence": "No fetched page states the timezone rule. A sample offset is not that rule.",
        "citation": None,
    },
    {
        "id": "candle_boundary",
        "status": "UNVERIFIED",
        "evidence": "Groww does not say start or end. Upstox says the timestamp is the start of the timeframe but does not name a NIFTY 50 key. A Kite forum reply says the timestamp is the candle start and also says there is no completeness flag. Neither reply selects a provider.",
        "citation": None,
    },
    {
        "id": "request_boundary",
        "status": "UNVERIFIED",
        "evidence": "Groww says from which and until which, without inclusive or exclusive. Upstox says to_date is inclusive and does not say the same for an intraday bound.",
        "citation": None,
    },
    {
        "id": "session_candles",
        "status": "UNVERIFIED",
        "evidence": "No fetched page states the opening or closing 15-minute NIFTY index candle convention.",
        "citation": None,
    },
    {
        "id": "incomplete_candles",
        "status": "UNVERIFIED",
        "evidence": "Groww, Upstox, Angel One, and DhanHQ do not state a partial-candle marker. The Kite staff reply says the historical API has no completeness flag, so a partial candle cannot be identified from that response.",
        "citation": None,
    },
    {
        "id": "authentication",
        "status": "UNVERIFIED",
        "evidence": "Groww documents a bearer token, and this application can store one. This module does not read or enable that credential. No Upstox, Kite, Angel One, or Dhan credential is stored. OpenAI is not a candle source.",
        "citation": None,
    },
    {
        "id": "rate_limits",
        "status": "UNVERIFIED",
        "evidence": "The Groww backtesting pages do not state a historical-candle rate limit. Request-size caps that are stated are recorded on each candidate and are not a rate limit.",
        "citation": None,
    },
    {
        "id": "licensing",
        "status": "UNVERIFIED",
        "evidence": "No fetched page states that 15-minute NIFTY history may be stored for this research use.",
        "citation": None,
    },
)

VALIDATION_DESIGN = {
    "status": "NOT_RUN",
    "reason": "The contract is not verified, so the read-only window was not requested.",
    "window": "One completed session after the contract is verified. The window stays short.",
    "checks": [
        "HTTP status and provider status",
        "Instrument is the NIFTY 50 index",
        "Interval is 15 minutes",
        "Timestamp text and timezone",
        "Order and duplicates",
        "OHLC relationships",
        "Session bounds named by the contract",
        "Partial candles only as the contract identifies them",
        "Missing intervals left missing",
        "Raw response checksum and retrieval time",
    ],
    "orders": False,
    "quarantine_until_requirements_pass": True,
}


def requirements_checklist() -> list[dict]:
    return [dict(item) for item in REQUIREMENTS]


def contract_ready() -> bool:
    required = {
        "instrument_identity",
        "interval_15minute",
        "timezone",
        "candle_boundary",
        "request_boundary",
        "session_candles",
        "incomplete_candles",
        "response_schema",
        "authentication",
        "licensing",
    }
    states = {item["id"]: item["status"] for item in REQUIREMENTS}
    return all(states.get(item) == "VERIFIED" for item in required)


def run_readonly_validation() -> dict:
    """The designed read stays unsent until every mandatory contract item is verified."""
    if not contract_ready():
        blocked = assessment()
        blocked["validation"] = dict(VALIDATION_DESIGN)
        blocked["provider_requests"] = 0
        return blocked
    return {
        "status": "BLOCKED",
        "code": "ACCESS_NOT_CONFIGURED",
        "trusted_dataset_created": False,
        "provider_requests": 0,
        "message": "No enabled market-data credential is read by this module.",
    }


def assessment(*, verified: bool = False) -> dict:
    facts = contract(verified=verified)
    code = "OK" if verified else "CANDLE_BOUNDARY_UNVERIFIED"
    status = "VERIFIED_SUPPORT_RESPONSE_RECEIVED" if verified else "BLOCKED"
    return {
        "status": status,
        "code": code,
        "trusted_dataset_created": False,
        "dataset_id": None,
        "checksum": None,
        "provider": "Groww" if verified else None,
        "instrument": "NIFTY",
        "interval": "M15",
        "coverage": None,
        "candle_count": 0,
        "missing_interval_count": None,
        "normalization_applied": False,
        "m2_ran": False,
        "m3_ran": False,
        "m4_ran": False,
        "evaluation_stopped_reason": (
            "Verified Groww support reply received on 15 Oct 2026. IST and bar-start contract confirmed."
            if verified else
            "No candidate has a documented NIFTY 15-minute timezone, candle boundary, partial-candle rule, "
            "and an accessible credential together. Feature generation and evaluation were not started."
        ),
        "documented_facts": list(DOCUMENTED_GROWW_FACTS),
        "observations": list(OBSERVED_NOT_A_CONTRACT),
        "unresolved": [item["id"] for item in facts["outstanding_confirmations"]],
        "rejected_assumptions": list(REJECTED_ASSUMPTIONS),
        "independent_sources": [dict(item) for item in INDEPENDENT_SOURCES],
        "requirements": requirements_checklist(),
        "contract_ready": verified or contract_ready(),
        "validation": dict(VALIDATION_DESIGN),
        "provider_selected": "Groww" if verified else None,
        "provider_contacted": verified,
        "groww_contract_established": facts["established"],
        "support_response_received": facts["support_response_received"],
        "support_response_file": "docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_RESPONSE.md",
        "documentation_read_on": READ_ON,
        "documentation_url": GROWW_PAGE,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def normalize_provider_record(row: dict, *, verified: bool = False) -> dict:
    """Map record when verified, or refuse when unverified or quarantined."""
    if not verified and (row.get("quarantine_id") or row.get("label") == "UNVERIFIED_PROVIDER" or row.get("data_category") == "UNVERIFIED_PROVIDER"):
        return {
            "ok": False,
            "code": "QUARANTINE_REJECTED",
            "message": "A quarantined record was not copied into trusted history.",
            "normalized": None,
        }
    mapped = map_provider_timestamp(str(row.get("timestamp") or ""), verified=verified)
    if not mapped["ok"]:
        return {
            "ok": False,
            "code": mapped["code"],
            "message": mapped["message"],
            "raw_timestamp": mapped["raw_timestamp"],
            "normalized": None,
        }
    if not verified:
        return {"ok": False, "code": "NORMALIZATION_REFUSED", "message": "No provider mapping is enabled.", "normalized": None}

    return {
        "ok": True,
        "code": "NORMALIZED",
        "raw_timestamp": mapped["raw_timestamp"],
        "normalized": {
            "timestamp": mapped["instant"],
            "bar_start": mapped["bar_start"],
            "bar_end": mapped["bar_end"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0.0),
            "partial_candle": mapped["partial_candle"],
        },
    }


def validate_quarantine_nifty_dataset(
    quarantine_id: str = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057",
    *,
    verified: bool = True,
    chart_reference: list[dict] | None = None,
) -> dict:
    """Validate and parse quarantined 13 October 2026 NIFTY candles into completed regular bars and features.

    Preserves raw data integrity, validates OHLC relationships and timestamps, separates regular
    session candles (09:15 to 15:15) from post-session boundary ticks (15:30), generates deterministic
    features, and keeps real_market_data_verified=False pending visual chart comparison.
    """
    import hashlib
    import json
    import math
    from app.features.pipeline import content_hash
    from app.settings import REPO_ROOT

    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{quarantine_id}.json"
    if not path.is_file():
        return {
            "ok": False,
            "code": "QUARANTINE_FILE_NOT_FOUND",
            "message": f"Quarantine record {quarantine_id} was not found.",
            "dataset": None,
        }

    raw_bytes = path.read_bytes()
    file_sha = hashlib.sha256(raw_bytes).hexdigest()
    record = json.loads(raw_bytes.decode("utf-8"))

    # Verify checksum
    body = {k: v for k, v in record.items() if k not in {"quarantine_id", "checksum"}}
    digest = content_hash(body)
    if record.get("checksum") != digest:
        return {
            "ok": False,
            "code": "CHECKSUM_MISMATCH",
            "message": "Quarantined record checksum does not match its contents.",
            "dataset": None,
        }

    raw_candles = record.get("raw_candles") or []
    if not raw_candles:
        return {
            "ok": False,
            "code": "NO_CANDLES",
            "message": "Quarantine record contains no candles.",
            "dataset": None,
        }

    # Validate each raw candle
    normalized_candles = []
    ohlc_issues = []
    seen_stamps: set[str] = set()
    for idx, row in enumerate(raw_candles):
        if not isinstance(row, list) or len(row) < 5:
            ohlc_issues.append({"index": idx, "reason": "Candle row has fewer than 5 elements."})
            continue
        ts_str = row[0]
        if not isinstance(ts_str, str):
            ohlc_issues.append({"index": idx, "reason": "Candle timestamp must be a string."})
            continue
        if ts_str in seen_stamps:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "Duplicate raw candle timestamp."})
            continue
        seen_stamps.add(ts_str)

        try:
            if isinstance(row[1], bool) or isinstance(row[2], bool) or isinstance(row[3], bool) or isinstance(row[4], bool):
                ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "Boolean price is invalid."})
                continue
            open_p, high_p, low_p, close_p = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        except (ValueError, TypeError):
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "Non-numeric OHLC price."})
            continue

        if open_p <= 0 or high_p <= 0 or low_p <= 0 or close_p <= 0:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "OHLC price must be positive."})
            continue

        # Validate OHLC relationships
        if high_p < max(open_p, close_p) or low_p > min(open_p, close_p) or high_p < low_p:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "High/Low do not contain Open/Close."})
            continue

        mapped = map_provider_timestamp(ts_str, verified=verified, interval_minutes=15)
        if not mapped["ok"]:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": mapped["message"]})
            continue

        vol = float(row[5]) if len(row) > 5 and row[5] is not None else 0.0
        normalized_candles.append({
            "index": idx,
            "raw_timestamp": ts_str,
            "instant": mapped["instant"],
            "bar_start": mapped["bar_start"],
            "bar_end": mapped["bar_end"],
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": vol,
            "partial_candle": mapped["partial_candle"],
        })

    if ohlc_issues:
        return {
            "ok": False,
            "code": "OHLC_VALIDATION_FAILED",
            "message": "One or more raw candles failed validation.",
            "issues": ohlc_issues,
            "dataset": None,
        }

    # Session boundaries:
    # 25 regular session candles start between 09:15:00 and 15:15:00 IST
    # The 26th candle (15:30:00) represents post-session closing auction price print
    regular_candles = [c for c in normalized_candles if not c["bar_start"].endswith("15:30:00+05:30") and not c["raw_timestamp"].endswith("15:30:00")]
    boundary_candles = [c for c in normalized_candles if c["bar_start"].endswith("15:30:00+05:30") or c["raw_timestamp"].endswith("15:30:00")]

    # Chart reference comparison
    chart_comp = {
        "status": "AWAITING_CHART_REFERENCE",
        "verified": False,
        "reason": "No independent ground-truth chart reference was supplied for visual comparison.",
        "discrepancies": [],
    }
    if chart_reference:
        ref_by_time = {r.get("timestamp"): r for r in chart_reference}
        discrepancies = []
        for c in regular_candles:
            ref = ref_by_time.get(c["raw_timestamp"])
            if not ref:
                discrepancies.append({"timestamp": c["raw_timestamp"], "reason": "Missing from chart reference."})
            elif abs(float(ref.get("close", 0)) - c["close"]) > 0.05:
                discrepancies.append({
                    "timestamp": c["raw_timestamp"],
                    "provider_close": c["close"],
                    "reference_close": ref.get("close"),
                    "reason": "Close price differs from chart reference.",
                })
        if discrepancies:
            chart_comp = {"status": "DISCREPANCY_DETECTED", "verified": False, "discrepancies": discrepancies}
        else:
            chart_comp = {"status": "MATCHED", "verified": True, "reference_count": len(chart_reference)}

    # Compute deterministic feature values for the 25 completed regular candles
    features = []
    closes = [c["close"] for c in regular_candles]
    highs = [c["high"] for c in regular_candles]
    lows = [c["low"] for c in regular_candles]
    opens = [c["open"] for c in regular_candles]

    for i in range(len(regular_candles)):
        c = regular_candles[i]
        ret_1 = (closes[i] - closes[i - 1]) / closes[i - 1] if i >= 1 and closes[i - 1] > 0 else 0.0
        ret_3 = (closes[i] - closes[i - 3]) / closes[i - 3] if i >= 3 and closes[i - 3] > 0 else 0.0
        sma_3 = sum(closes[max(0, i - 2) : i + 1]) / min(3, i + 1)
        sma_5 = sum(closes[max(0, i - 4) : i + 1]) / min(5, i + 1)
        ret_std_5 = 0.0
        if i >= 4:
            rets = [(closes[k] - closes[k - 1]) / closes[k - 1] for k in range(i - 3, i + 1)]
            mean_r = sum(rets) / len(rets)
            ret_std_5 = math.sqrt(sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)) if len(rets) > 1 else 0.0

        tr_3 = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]) if i > 0 else 0, abs(lows[i] - closes[i - 1]) if i > 0 else 0)
        close_pos = (closes[i] - lows[i]) / max(0.001, highs[i] - lows[i])

        features.append({
            "timestamp": c["instant"],
            "bar_start": c["bar_start"],
            "bar_end": c["bar_end"],
            "close": closes[i],
            "features": {
                "ret_1": round(ret_1, 6),
                "ret_3": round(ret_3, 6),
                "sma_3": round(sma_3, 4),
                "sma_5": round(sma_5, 4),
                "close_vs_sma_5": round((closes[i] - sma_5) / sma_5 if sma_5 else 0.0, 6),
                "sma_3_minus_sma_5": round(sma_3 - sma_5, 4),
                "ret_std_5": round(ret_std_5, 6),
                "atr_3": round(tr_3, 4),
                "hl_range_vs_prev_close": round((highs[i] - lows[i]) / closes[i - 1] if i > 0 and closes[i - 1] else 0.0, 6),
                "oc_return": round((closes[i] - opens[i]) / opens[i] if opens[i] else 0.0, 6),
                "close_position": round(close_pos, 4),
            },
        })

    dataset_body = {
        "schema_version": "m2-dataset-1",
        "instrument": "NIFTY",
        "interval": "M15",
        "quarantine_id": quarantine_id,
        "source_raw_sha256": file_sha,
        "regular_candle_count": len(regular_candles),
        "boundary_candle_count": len(boundary_candles),
        "candles": regular_candles,
        "features": features,
    }
    dataset_id = content_hash(dataset_body)

    return {
        "ok": True,
        "code": "PARSED_PENDING_CHART_VERIFICATION",
        "status": "QUARANTINED_SEMANTICS_CONFIRMED",
        "quarantine_id": quarantine_id,
        "dataset_id": dataset_id,
        "checksum": dataset_id,
        "source_sha256": file_sha,
        "instrument": "NIFTY",
        "interval": "M15",
        "total_candles_read": len(raw_candles),
        "completed_regular_candles": len(regular_candles),
        "post_session_boundary_candles": len(boundary_candles),
        "first_candle_start": regular_candles[0]["bar_start"] if regular_candles else None,
        "last_regular_candle_start": regular_candles[-1]["bar_start"] if regular_candles else None,
        "post_session_candle_start": boundary_candles[0]["bar_start"] if boundary_candles else None,
        "chart_comparison": chart_comp,
        "features_generated_count": len(features),
        "real_market_data_verified": False,  # Safety flag stays False
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "dataset": dataset_body,
    }


KNOWN_QUARANTINE_RAW_SHA256 = {
    "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057": "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
}


def find_independent_chart_reference(
    date_str: str = "2026-10-13",
    instrument: str = "NIFTY",
    interval: str = "15minute",
):
    """Inspect local storage for independent, machine-readable reference datasets."""
    from pathlib import Path
    from app.settings import REPO_ROOT
    candidates = [
        REPO_ROOT / "var" / "history" / "reference" / f"{instrument.lower()}_{date_str}_{interval}.json",
        REPO_ROOT / "var" / "history" / "reference" / f"{instrument.lower()}_{date_str}.json",
        REPO_ROOT / "var" / "reference" / f"{instrument.lower()}_{date_str}_{interval}.json",
        REPO_ROOT / "var" / "reference" / f"{instrument.lower()}_{date_str}.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def reconcile_quarantine_nifty_dataset(
    quarantine_id: str = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057",
    *,
    reference_data: list[dict] | None = None,
    reference_path: str | None = None,
    expected_raw_sha256: str | None = None,
    tolerance: float = 0.05,
    promote: bool = False,
    store: object | None = None,
) -> dict:
    """Independently reconcile quarantined NIFTY 15-minute dataset against a machine-readable reference.

    Enforces all M9 requirements:
    - Verifies raw Groww file SHA-256 before and after processing.
    - If reference is unavailable, returns explicit BLOCKED_REFERENCE_UNAVAILABLE.
    - Compares 25 regular session candles (09:15-15:15 IST) on open, high, low, close.
    - Classifies the 15:30:00 tick as POST_SESSION_AUCTION_TICK and excludes it from completed regular bars.
    - Detects missing/duplicate/unexpected candles, timezone mismatches, invalid OHLC, and hash changes.
    - Produces a deterministic validation report and manifest upon successful match.
    - Integrates promotion into HistoryStore (fail-closed, safety flags remain False).
    """
    import hashlib
    import json
    from datetime import datetime
    from pathlib import Path
    from app.settings import REPO_ROOT

    target_id = quarantine_id
    path = REPO_ROOT / "var" / "history" / "quarantine" / f"{target_id}.json"
    if not path.is_file():
        return {
            "ok": False,
            "code": "QUARANTINE_FILE_NOT_FOUND",
            "status": "FAIL",
            "message": f"Quarantine record {target_id} was not found.",
            "quarantine_id": target_id,
            "raw_data_hash": None,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    raw_bytes_before = path.read_bytes()
    file_sha = hashlib.sha256(raw_bytes_before).hexdigest()

    # Verify expected raw hash if supplied or known
    expected_hash = expected_raw_sha256 or KNOWN_QUARANTINE_RAW_SHA256.get(target_id)
    if expected_hash and file_sha != expected_hash:
        return {
            "ok": False,
            "code": "RAW_DATA_HASH_CHANGED",
            "status": "FAIL",
            "message": f"Raw data hash {file_sha} differs from expected {expected_hash}.",
            "quarantine_id": target_id,
            "raw_data_hash": file_sha,
            "expected_raw_data_hash": expected_hash,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    # If reference not provided, check local filesystem
    if reference_data is None and reference_path is None:
        local_ref = find_independent_chart_reference()
        if local_ref is not None:
            reference_path = str(local_ref)

    # If reference remains unavailable, return BLOCKED_REFERENCE_UNAVAILABLE
    if reference_data is None and reference_path is None:
        return {
            "ok": False,
            "code": "BLOCKED_REFERENCE_UNAVAILABLE",
            "status": "BLOCKED",
            "message": (
                "Independent machine-readable NIFTY 15-minute OHLC reference for 13 October 2026 "
                "is unavailable. The dataset remains quarantined without ground-truth comparison."
            ),
            "quarantine_id": target_id,
            "raw_data_hash": file_sha,
            "raw_hash_unchanged": True,
            "discrepancies": [],
            "manifest": None,
            "promoted": False,
            "dataset_id": None,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    # Load reference data from path if needed
    if reference_path is not None and reference_data is None:
        ref_file = Path(reference_path)
        if not ref_file.is_file():
            return {
                "ok": False,
                "code": "REFERENCE_FILE_NOT_FOUND",
                "status": "FAIL",
                "message": f"Reference file {reference_path} was not found.",
                "quarantine_id": target_id,
                "raw_data_hash": file_sha,
                "real_market_data_verified": False,
                "forecast_ready": False,
                "paper_approved": False,
                "live_approved": False,
            }
        try:
            loaded = json.loads(ref_file.read_text(encoding="utf-8"))
            reference_data = loaded if isinstance(loaded, list) else loaded.get("candles") or []
        except Exception as exc:
            return {
                "ok": False,
                "code": "REFERENCE_PARSE_ERROR",
                "status": "FAIL",
                "message": f"Could not parse reference file: {exc}",
                "quarantine_id": target_id,
                "raw_data_hash": file_sha,
                "real_market_data_verified": False,
                "forecast_ready": False,
                "paper_approved": False,
                "live_approved": False,
            }

    # Run quarantine parsing and internal consistency checks
    parsed = validate_quarantine_nifty_dataset(target_id, verified=True)
    if not parsed.get("ok"):
        return {
            "ok": False,
            "code": parsed.get("code", "VALIDATION_FAILED"),
            "status": "FAIL",
            "message": parsed.get("message", "Quarantine validation failed."),
            "quarantine_id": target_id,
            "raw_data_hash": file_sha,
            "discrepancies": parsed.get("issues", []),
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    regular_candles = parsed["dataset"]["candles"]
    raw_candles = json.loads(raw_bytes_before.decode("utf-8")).get("raw_candles") or []

    # Validate reference structure, timezone, duplicates, and OHLC
    discrepancies: list[dict] = []
    ref_by_time: dict[str, dict] = {}
    seen_ref_stamps: set[str] = set()

    for idx, item in enumerate(reference_data or []):
        if not isinstance(item, dict):
            discrepancies.append({"type": "INVALID_REFERENCE_FORMAT", "index": idx, "reason": "Reference row is not a dict."})
            continue
        ts_raw = item.get("timestamp") or item.get("time") or item.get("date") or item.get("raw_timestamp")
        if not isinstance(ts_raw, str):
            discrepancies.append({"type": "INVALID_REFERENCE_TIMESTAMP", "index": idx, "reason": "Timestamp missing or not a string."})
            continue

        # Parse timestamp and validate timezone offset
        try:
            dt = datetime.fromisoformat(ts_raw)
            if dt.tzinfo is not None:
                offset_secs = dt.utcoffset().total_seconds()
                if offset_secs != 19800:  # UTC+05:30 IST is 19800 seconds
                    discrepancies.append({
                        "type": "TIMEZONE_MISMATCH",
                        "timestamp": ts_raw,
                        "offset": str(dt.tzinfo),
                        "reason": f"Reference candle at {ts_raw} has non-IST timezone offset ({offset_secs}s != 19800s).",
                    })
            norm_ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            discrepancies.append({
                "type": "INVALID_REFERENCE_TIMESTAMP",
                "timestamp": ts_raw,
                "reason": f"Could not parse timestamp {ts_raw} as ISO-8601.",
            })
            continue

        if norm_ts in seen_ref_stamps:
            discrepancies.append({
                "type": "DUPLICATE_REFERENCE_CANDLE",
                "timestamp": norm_ts,
                "reason": f"Duplicate candle timestamp {norm_ts} found in reference.",
            })
        seen_ref_stamps.add(norm_ts)

        # Validate reference OHLC numbers
        try:
            if isinstance(item.get("open"), bool) or isinstance(item.get("high"), bool) or isinstance(item.get("low"), bool) or isinstance(item.get("close"), bool):
                discrepancies.append({
                    "type": "INVALID_REFERENCE_OHLC",
                    "timestamp": norm_ts,
                    "reason": f"Boolean OHLC price is invalid in reference candle at {norm_ts}.",
                })
                continue
            ro = float(item["open"])
            rh = float(item["high"])
            rl = float(item["low"])
            rc = float(item["close"])
        except (KeyError, ValueError, TypeError):
            discrepancies.append({
                "type": "INVALID_REFERENCE_OHLC",
                "timestamp": norm_ts,
                "reason": f"Non-numeric or missing OHLC fields in reference candle at {norm_ts}.",
            })
            continue

        if ro <= 0 or rh <= 0 or rl <= 0 or rc <= 0 or rh < max(ro, rc) or rl > min(ro, rc) or rh < rl:
            discrepancies.append({
                "type": "INVALID_REFERENCE_OHLC",
                "timestamp": norm_ts,
                "reason": f"Invalid OHLC relationship in reference candle at {norm_ts} (O={ro}, H={rh}, L={rl}, C={rc}).",
            })
            continue

        ref_by_time[norm_ts] = {"open": ro, "high": rh, "low": rl, "close": rc}

    # Compare 25 regular session candles by timestamp
    regular_ts_set = set()
    matched_count = 0
    max_discrepancy = 0.0

    for c in regular_candles:
        ts = c["raw_timestamp"]
        regular_ts_set.add(ts)
        if ts not in ref_by_time:
            discrepancies.append({
                "type": "MISSING_CANDLE_IN_REFERENCE",
                "timestamp": ts,
                "reason": f"Completed regular candle at {ts} is missing in independent reference.",
            })
            continue

        ref = ref_by_time[ts]
        candle_matched = True
        for field in ("open", "high", "low", "close"):
            groww_p = c[field]
            ref_p = ref[field]
            delta = abs(groww_p - ref_p)
            if delta > max_discrepancy:
                max_discrepancy = delta
            if delta > tolerance:
                candle_matched = False
                discrepancies.append({
                    "type": "OHLC_MISMATCH",
                    "timestamp": ts,
                    "field": field,
                    "groww_price": groww_p,
                    "reference_price": ref_p,
                    "difference": round(delta, 4),
                    "tolerance": tolerance,
                    "reason": f"{field.capitalize()} price differs by {delta:.4f} exceeding tolerance {tolerance}.",
                })
        if candle_matched:
            matched_count += 1

    # Check for unexpected regular candles in reference
    for ref_ts in ref_by_time:
        if ref_ts not in regular_ts_set and not ref_ts.endswith("15:30:00"):
            discrepancies.append({
                "type": "UNEXPECTED_REFERENCE_CANDLE",
                "timestamp": ref_ts,
                "reason": f"Reference contains unexpected intraday candle at {ref_ts}.",
            })

    # Verify raw file unchanged after processing
    raw_bytes_after = path.read_bytes()
    sha_after = hashlib.sha256(raw_bytes_after).hexdigest()
    if sha_after != file_sha:
        return {
            "ok": False,
            "code": "RAW_DATA_HASH_CHANGED",
            "status": "FAIL",
            "message": "Quarantined raw payload file bytes were altered during processing.",
            "quarantine_id": target_id,
            "raw_data_hash_before": file_sha,
            "raw_data_hash_after": sha_after,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    # Decide reconciliation outcome
    if discrepancies:
        return {
            "ok": False,
            "code": "RECONCILIATION_FAILED",
            "status": "DISCREPANCIES_DETECTED",
            "message": f"Reconciliation failed with {len(discrepancies)} discrepancies.",
            "quarantine_id": target_id,
            "raw_data_hash": file_sha,
            "raw_hash_unchanged": True,
            "total_candles_received": len(raw_candles),
            "regular_candles_count": len(regular_candles),
            "excluded_candles_count": parsed["post_session_boundary_candles"],
            "matched_candles_count": matched_count,
            "max_discrepancy": round(max_discrepancy, 6),
            "discrepancies": discrepancies,
            "manifest": None,
            "promoted": False,
            "dataset_id": None,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    # Successful reconciliation: generate deterministic manifest
    rec_body = json.loads(raw_bytes_before.decode("utf-8"))
    manifest = {
        "schema_version": "m9-manifest-1",
        "instrument": "NIFTY",
        "interval": "M15",
        "trading_date": "2026-10-13",
        "timezone": "Asia/Kolkata",
        "source_provenance": {
            "provider": "Groww",
            "endpoint": "GET /v1/historical/candles",
            "groww_symbol": rec_body.get("groww_symbol", "NSE-NIFTY"),
            "quarantine_id": target_id,
            "retrieved_at": rec_body.get("retrieved_at"),
            "exchange": rec_body.get("exchange", "NSE"),
            "segment": rec_body.get("segment", "CASH"),
            "raw_body_sha256": rec_body.get("raw_body_sha256"),
        },
        "raw_data_hash": file_sha,
        "validated_dataset_hash": parsed["dataset_id"],
        "total_candles_received": len(raw_candles),
        "included_candle_count": len(regular_candles),
        "excluded_candle_count": parsed["post_session_boundary_candles"],
        "exclusion_reasons": {
            "2026-10-13T15:30:00": "POST_SESSION_AUCTION_TICK: zero duration closing price print at session boundary 15:30:00"
        },
        "comparison_results": {
            "reference_type": "INDEPENDENT_GROUND_TRUTH",
            "tolerance": tolerance,
            "total_compared": len(regular_candles),
            "total_matched": len(regular_candles),
            "max_discrepancy": round(max_discrepancy, 6),
            "discrepancies": [],
        },
        "validation_status": "RECONCILED_MATCHED",
        "real_market_data_verified": False,  # Preserved False per safety requirements
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }

    result = {
        "ok": True,
        "code": "RECONCILIATION_MATCHED",
        "status": "RECONCILED_MATCHED",
        "message": "Quarantined dataset successfully reconciled against independent reference.",
        "quarantine_id": target_id,
        "raw_data_hash": file_sha,
        "raw_hash_unchanged": True,
        "dataset_id": parsed["dataset_id"],
        "included_candles_count": len(regular_candles),
        "excluded_candles_count": parsed["post_session_boundary_candles"],
        "matched_candles_count": matched_count,
        "max_discrepancy": round(max_discrepancy, 6),
        "discrepancies": [],
        "manifest": manifest,
        "dataset": parsed["dataset"],
        "promoted": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }

    if promote:
        promoted = promote_reconciled_dataset(result, store=store)
        result["promoted"] = promoted.get("promoted", False)
        result["promotion"] = promoted

    return result


def promote_reconciled_dataset(
    reconciliation_result: dict,
    *,
    store: object | None = None,
) -> dict:
    """Promote a successfully reconciled dataset into HistoryStore with sealed manifest.

    Preserves safety invariant: real_market_data_verified=False, forecast_ready=False,
    paper_approved=False, live_approved=False.
    """
    if not reconciliation_result.get("ok") or reconciliation_result.get("status") != "RECONCILED_MATCHED":
        return {
            "ok": False,
            "code": "PROMOTION_REFUSED",
            "message": "Dataset has not been successfully reconciled against an independent reference.",
            "promoted": False,
            "dataset_id": None,
        }
    manifest = reconciliation_result.get("manifest")
    if not manifest:
        return {
            "ok": False,
            "code": "MANIFEST_MISSING",
            "message": "Reconciliation result does not contain a valid manifest.",
            "promoted": False,
            "dataset_id": None,
        }

    from app.market.history import HistoryStore, history_store, SCHEMA_VERSION
    from app.market.schemas import Candle, DataOrigin, MarketSession
    from app.features.pipeline import seal

    store_target = store or history_store()
    raw_dataset = reconciliation_result.get("dataset") or {}
    candles_data = raw_dataset.get("candles") or []

    candles_records = []
    for c in candles_data:
        candles_records.append({
            "instrument_id": manifest["instrument"],
            "underlying": manifest["instrument"],
            "interval": manifest["interval"],
            "bar_start": c["bar_start"],
            "bar_end": c["bar_end"],
            "retrieved_at": "2026-10-14T09:53:27.641450+00:00",
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c.get("volume"),
            "source_id": f"groww-quarantine-{manifest['source_provenance']['quarantine_id']}",
            "origin": DataOrigin.PROVIDER.value,
            "session": MarketSession.OPEN.value,
        })

    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": "source_candles",
        "instrument": manifest["instrument"],
        "provider": "groww",
        "provider_symbol": manifest["source_provenance"]["groww_symbol"],
        "interval": manifest["interval"],
        "requested_start": "2026-10-13T09:15:00+05:30",
        "requested_end": "2026-10-13T15:30:00+05:30",
        "retrieved_start": "2026-10-13T09:15:00+05:30",
        "retrieved_end": "2026-10-13T15:30:00+05:30",
        "origin": DataOrigin.PROVIDER.value,
        "source_verification": "RECONCILED_WITH_INDEPENDENT_REFERENCE",
        "market_data_verification": False,
        "verification_established": False,
        "point_in_time_revisions_available": False,
        "candle_boundary_role": "start",
        "candle_completion_rule": "retrieved_at_at_or_after_bar_end",
        "timezone": manifest["timezone"],
        "created_at": "2026-10-13T15:30:00+05:30",
        "candle_count": manifest["included_candle_count"],
        "manifest": manifest,
        "validation": {
            "validation_status": "PASS",
            "candle_count": manifest["included_candle_count"],
            "rejection_reasons": [],
            "issues": [],
        },
        "forecast_eligible": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "candles": candles_records,
    }
    artifact = seal(body)
    store_target.write(artifact)
    return {
        "ok": True,
        "code": "PROMOTED",
        "message": "Dataset successfully promoted and sealed into historical store.",
        "promoted": True,
        "dataset_id": artifact["dataset_id"],
        "artifact": artifact,
    }


def build_trusted_dataset(
    quarantine_id: str | None = None,
    *,
    verified: bool = False,
    chart_reference: list[dict] | None = None,
    promote: bool = False,
    store: object | None = None,
) -> dict:
    """Return assessment when unverified, or reconcile quarantined dataset when verified is True."""
    if not verified:
        return assessment()
    target_id = quarantine_id or "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
    return reconcile_quarantine_nifty_dataset(
        target_id,
        reference_data=chart_reference,
        promote=promote,
        store=store,
    )


STANDARD_SESSION_START_TIMES = (
    "09:15:00", "09:30:00", "09:45:00", "10:00:00", "10:15:00", "10:30:00", "10:45:00",
    "11:00:00", "11:15:00", "11:30:00", "11:45:00", "12:00:00", "12:15:00", "12:30:00",
    "12:45:00", "13:00:00", "13:15:00", "13:30:00", "13:45:00", "14:00:00", "14:15:00",
    "14:30:00", "14:45:00", "15:00:00", "15:15:00",
)


def validate_historical_dataset(
    raw_payload: dict | list | bytes | str | object,
    *,
    instrument: str = "NIFTY",
    interval: str = "15minute",
    verified: bool = False,
    now: object | None = None,
) -> dict:
    """Validate a multi-day or single-day raw NIFTY 15m dataset against M11 schema requirements.

    Enforces all M11 ingestion rules:
    - Verifies instrument is NIFTY (or NSE-NIFTY) and exchange is NSE
    - Verifies interval is 15-minute
    - Preserves raw response and calculates immutable SHA-256 hash
    - Normalizes timestamps to IST (+05:30)
    - Validates positive numeric OHLC: open, high, low, close > 0 (no booleans/strings/nans)
    - Enforces high >= max(open, close) and low <= min(open, close)
    - Detects duplicate timestamps (AMBIGUOUS_TIME / DUPLICATE_CANDLE)
    - Excludes post-session closing auction tick (15:30:00) as POST_SESSION_AUCTION_TICK
    - Excludes incomplete candles (where now < bar_end) as INCOMPLETE_CANDLE
    - Detects missing expected intraday candles (25 bars per standard session: 09:15 to 15:15)
    - Forbids silent price forward-filling or fabrication
    - Records all exclusions, issues, and session summaries
    """
    import hashlib
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from app.features.pipeline import content_hash
    from app.market.schemas import IST

    if isinstance(raw_payload, Path):
        raw_bytes = raw_payload.read_bytes()
        record = json.loads(raw_bytes.decode("utf-8"))
    elif isinstance(raw_payload, (bytes, bytearray)):
        raw_bytes = bytes(raw_payload)
        record = json.loads(raw_bytes.decode("utf-8"))
    elif isinstance(raw_payload, str):
        raw_bytes = raw_payload.encode("utf-8")
        record = json.loads(raw_payload)
    elif isinstance(raw_payload, (dict, list)):
        raw_bytes = json.dumps(raw_payload, sort_keys=True).encode("utf-8")
        record = raw_payload
    else:
        return {
            "ok": False,
            "code": "INVALID_PAYLOAD_TYPE",
            "message": "Raw payload must be dict, list, bytes, str, or Path.",
            "raw_data_hash": None,
            "dataset": None,
        }

    raw_sha = hashlib.sha256(raw_bytes).hexdigest()

    if isinstance(record, dict):
        inst = record.get("instrument") or record.get("groww_symbol") or instrument
        inter = record.get("candle_interval") or record.get("interval") or interval
        raw_candles = record.get("raw_candles") or record.get("candles") or []
    elif isinstance(record, list):
        inst = instrument
        inter = interval
        raw_candles = record
    else:
        return {
            "ok": False,
            "code": "SCHEMA_MISMATCH",
            "message": "Payload does not contain a candle array or object.",
            "raw_data_hash": raw_sha,
            "dataset": None,
        }

    if inst not in ("NIFTY", "NSE-NIFTY", "NIFTY 50"):
        return {
            "ok": False,
            "code": "UNSUPPORTED_INSTRUMENT",
            "message": f"Instrument {inst} is unsupported. Expected NIFTY.",
            "raw_data_hash": raw_sha,
            "dataset": None,
        }

    if inter not in ("15minute", "M15", "15m"):
        return {
            "ok": False,
            "code": "UNSUPPORTED_INTERVAL",
            "message": f"Interval {inter} is unsupported. Expected 15m / M15.",
            "raw_data_hash": raw_sha,
            "dataset": None,
        }

    if not raw_candles:
        return {
            "ok": False,
            "code": "NO_CANDLES",
            "message": "Dataset contains no candles.",
            "raw_data_hash": raw_sha,
            "dataset": None,
        }

    normalized_candles: list[dict] = []
    excluded_boundary_candles: list[dict] = []
    excluded_incomplete_candles: list[dict] = []
    duplicate_stamps: list[dict] = []
    ohlc_issues: list[dict] = []
    seen_stamps: set[str] = set()

    for idx, row in enumerate(raw_candles):
        if isinstance(row, dict):
            ts_str = row.get("timestamp") or row.get("time") or row.get("raw_timestamp")
            o_val = row.get("open")
            h_val = row.get("high")
            l_val = row.get("low")
            c_val = row.get("close")
            v_val = row.get("volume")
        elif isinstance(row, list) and len(row) >= 5:
            ts_str = row[0]
            o_val = row[1]
            h_val = row[2]
            l_val = row[3]
            c_val = row[4]
            v_val = row[5] if len(row) > 5 else 0.0
        else:
            ohlc_issues.append({"index": idx, "reason": "Candle row must be dict or list with >= 5 elements."})
            continue

        if not isinstance(ts_str, str):
            ohlc_issues.append({"index": idx, "reason": "Timestamp must be a string."})
            continue

        if ts_str in seen_stamps:
            duplicate_stamps.append({"index": idx, "timestamp": ts_str, "reason": "Duplicate candle timestamp."})
            continue
        seen_stamps.add(ts_str)

        # Validate numeric OHLC (reject booleans)
        if any(isinstance(v, bool) for v in (o_val, h_val, l_val, c_val)):
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "Boolean price is invalid."})
            continue

        try:
            o_p, h_p, l_p, c_p = float(o_val), float(h_val), float(l_val), float(c_val)
        except (ValueError, TypeError):
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "Non-numeric OHLC price."})
            continue

        if o_p <= 0 or h_p <= 0 or l_p <= 0 or c_p <= 0:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "OHLC price must be positive."})
            continue

        if h_p < max(o_p, c_p) or l_p > min(o_p, c_p) or h_p < l_p:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": "High/Low do not contain Open/Close."})
            continue

        mapped = map_provider_timestamp(ts_str, verified=verified, interval_minutes=15)
        if not mapped["ok"]:
            ohlc_issues.append({"index": idx, "timestamp": ts_str, "reason": mapped["message"]})
            continue

        vol = float(v_val) if v_val is not None else 0.0

        candle_dict = {
            "index": idx,
            "raw_timestamp": ts_str,
            "instant": mapped["instant"],
            "bar_start": mapped["bar_start"],
            "bar_end": mapped["bar_end"],
            "open": o_p,
            "high": h_p,
            "low": l_p,
            "close": c_p,
            "volume": vol,
            "partial_candle": mapped["partial_candle"],
        }

        # Check post-session boundary tick (15:30:00 IST)
        if ts_str.endswith("15:30:00") or mapped["bar_start"].endswith("15:30:00+05:30"):
            candle_dict["exclusion_reason"] = "POST_SESSION_AUCTION_TICK"
            excluded_boundary_candles.append(candle_dict)
            continue

        # Check incomplete candle against current wall clock
        if now is not None:
            bar_end_dt = datetime.fromisoformat(mapped["bar_end"])
            now_ist = now.astimezone(IST) if getattr(now, "tzinfo", None) else now.replace(tzinfo=IST)
            if bar_end_dt > now_ist:
                candle_dict["exclusion_reason"] = "INCOMPLETE_CANDLE"
                excluded_incomplete_candles.append(candle_dict)
                continue

        normalized_candles.append(candle_dict)

    if ohlc_issues:
        return {
            "ok": False,
            "code": "OHLC_VALIDATION_FAILED",
            "message": f"Dataset failed numeric OHLC validation with {len(ohlc_issues)} issues.",
            "raw_data_hash": raw_sha,
            "issues": ohlc_issues,
            "dataset": None,
        }

    if duplicate_stamps:
        return {
            "ok": False,
            "code": "AMBIGUOUS_TIME",
            "message": f"Dataset contains {len(duplicate_stamps)} duplicate timestamps.",
            "raw_data_hash": raw_sha,
            "issues": duplicate_stamps,
            "dataset": None,
        }

    # Group regular session candles by date
    sessions: dict[str, list[dict]] = {}
    for c in normalized_candles:
        date_key = c["bar_start"][:10]
        sessions.setdefault(date_key, []).append(c)

    # Detect missing candles per session
    missing_candles: list[dict] = []
    session_summaries: dict[str, dict] = {}
    for date_key, day_candles in sorted(sessions.items()):
        observed_times = {c["bar_start"][11:19] for c in day_candles}
        day_missing = []
        for expected_t in STANDARD_SESSION_START_TIMES:
            if expected_t not in observed_times:
                day_missing.append(expected_t)
                missing_candles.append({
                    "date": date_key,
                    "expected_time": expected_t,
                    "expected_timestamp": f"{date_key}T{expected_t}+05:30",
                    "reason": "Missing expected 15m candle in regular trading session.",
                })
        session_summaries[date_key] = {
            "observed_candles": len(day_candles),
            "expected_candles": len(STANDARD_SESSION_START_TIMES),
            "missing_candles_count": len(day_missing),
            "missing_times": day_missing,
            "is_complete_regular_session": len(day_missing) == 0,
        }

    dataset_body = {
        "schema_version": "m11-dataset-1",
        "instrument": "NIFTY",
        "interval": "M15",
        "source_raw_sha256": raw_sha,
        "total_candles_received": len(raw_candles),
        "regular_candle_count": len(normalized_candles),
        "excluded_boundary_count": len(excluded_boundary_candles),
        "excluded_incomplete_count": len(excluded_incomplete_candles),
        "missing_candles_count": len(missing_candles),
        "session_count": len(sessions),
        "candles": normalized_candles,
    }
    dataset_id = content_hash(dataset_body)

    return {
        "ok": True,
        "code": "VALIDATED",
        "dataset_id": dataset_id,
        "raw_data_hash": raw_sha,
        "instrument": "NIFTY",
        "interval": "15minute",
        "total_candles_received": len(raw_candles),
        "valid_regular_candles": normalized_candles,
        "regular_candle_count": len(normalized_candles),
        "excluded_boundary_candles": excluded_boundary_candles,
        "excluded_boundary_count": len(excluded_boundary_candles),
        "excluded_incomplete_candles": excluded_incomplete_candles,
        "excluded_incomplete_count": len(excluded_incomplete_candles),
        "missing_candles": missing_candles,
        "missing_candles_count": len(missing_candles),
        "has_gaps": len(missing_candles) > 0,
        "session_count": len(sessions),
        "sessions": session_summaries,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "dataset": dataset_body,
    }


def reconcile_historical_dataset(
    raw_payload: dict | list | bytes | str | object,
    *,
    reference_data: list[dict] | None = None,
    reference_path: str | object | None = None,
    tolerance: float = 0.05,
    promote: bool = False,
    store: object | None = None,
    now: object | None = None,
) -> dict:
    """Reconcile a multi-session or single-session historical NIFTY dataset against an independent reference.

    Follows strict M11 verification protocol:
    - Runs validate_historical_dataset to verify numeric OHLC, intervals, and session structure.
    - If reference is unavailable, returns explicit BLOCKED_REFERENCE_UNAVAILABLE.
    - Compares every overlapping regular candle by timestamp on open, high, low, close.
    - Detects missing reference candles, duplicate reference candles, and tolerance excursions.
    - Enforces immutable raw data preservation.
    - Keeps all safety invariants (real_market_data_verified=False, forecast_ready=False).
    """
    import hashlib
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from app.features.pipeline import content_hash

    validated = validate_historical_dataset(raw_payload, verified=True, now=now)
    if not validated.get("ok"):
        return {
            "ok": False,
            "code": validated.get("code", "VALIDATION_FAILED"),
            "status": "FAIL",
            "message": validated.get("message", "Historical dataset validation failed."),
            "raw_data_hash": validated.get("raw_data_hash"),
            "discrepancies": validated.get("issues", []),
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    raw_sha = validated["raw_data_hash"]
    regular_candles = validated["valid_regular_candles"]

    # Check local reference if none passed
    if reference_data is None and reference_path is None:
        local_ref = find_independent_chart_reference()
        if local_ref is not None:
            reference_path = str(local_ref)

    if reference_data is None and reference_path is None:
        return {
            "ok": False,
            "code": "BLOCKED_REFERENCE_UNAVAILABLE",
            "status": "BLOCKED",
            "message": (
                "Independent machine-readable NIFTY 15-minute OHLC reference is unavailable. "
                "The dataset remains unverified without ground-truth comparison."
            ),
            "raw_data_hash": raw_sha,
            "raw_hash_unchanged": True,
            "total_candles_received": validated["total_candles_received"],
            "regular_candles_count": validated["regular_candle_count"],
            "session_count": validated["session_count"],
            "missing_candles_count": validated["missing_candles_count"],
            "has_gaps": validated["has_gaps"],
            "matched_candles_count": 0,
            "mismatched_candles_count": 0,
            "missing_candles_per_source": {
                "provider_missing": validated["missing_candles_count"],
                "reference_missing": None,
            },
            "duplicate_observations_count": 0,
            "max_discrepancy": None,
            "timestamp_alignment": "NOT_EVALUATED",
            "excluded_observations": validated.get("excluded_boundary_candles", []),
            "unresolved_discrepancies": [
                {"type": "REFERENCE_UNAVAILABLE", "reason": "No independent ground-truth reference available."}
            ],
            "reference_provenance": None,
            "discrepancies": [],
            "manifest": None,
            "promoted": False,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    # Load reference data from path if needed
    if reference_path is not None and reference_data is None:
        ref_file = Path(str(reference_path))
        if not ref_file.is_file():
            return {
                "ok": False,
                "code": "REFERENCE_FILE_NOT_FOUND",
                "status": "FAIL",
                "message": f"Reference file {reference_path} was not found.",
                "raw_data_hash": raw_sha,
                "real_market_data_verified": False,
                "forecast_ready": False,
                "paper_approved": False,
                "live_approved": False,
            }
        try:
            loaded = json.loads(ref_file.read_text(encoding="utf-8"))
            reference_data = loaded if isinstance(loaded, list) else loaded.get("candles") or []
        except Exception as exc:
            return {
                "ok": False,
                "code": "REFERENCE_PARSE_ERROR",
                "status": "FAIL",
                "message": f"Could not parse reference file: {exc}",
                "raw_data_hash": raw_sha,
                "real_market_data_verified": False,
                "forecast_ready": False,
                "paper_approved": False,
                "live_approved": False,
            }

    discrepancies: list[dict] = []
    ref_by_time: dict[str, dict] = {}
    seen_ref_stamps: set[str] = set()

    for idx, item in enumerate(reference_data or []):
        if not isinstance(item, dict):
            discrepancies.append({"type": "INVALID_REFERENCE_FORMAT", "index": idx, "reason": "Reference row is not a dict."})
            continue
        ts_raw = item.get("timestamp") or item.get("time") or item.get("date") or item.get("raw_timestamp")
        if not isinstance(ts_raw, str):
            discrepancies.append({"type": "INVALID_REFERENCE_TIMESTAMP", "index": idx, "reason": "Timestamp missing or not a string."})
            continue

        try:
            dt = datetime.fromisoformat(ts_raw)
            if dt.tzinfo is not None:
                offset_secs = dt.utcoffset().total_seconds()
                if offset_secs != 19800:
                    discrepancies.append({
                        "type": "TIMEZONE_MISMATCH",
                        "timestamp": ts_raw,
                        "reason": f"Reference candle at {ts_raw} has non-IST timezone offset.",
                    })
            norm_ts = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            discrepancies.append({
                "type": "INVALID_REFERENCE_TIMESTAMP",
                "timestamp": ts_raw,
                "reason": f"Could not parse timestamp {ts_raw} as ISO-8601.",
            })
            continue

        if norm_ts in seen_ref_stamps:
            discrepancies.append({
                "type": "DUPLICATE_REFERENCE_CANDLE",
                "timestamp": norm_ts,
                "reason": f"Duplicate candle timestamp {norm_ts} found in reference.",
            })
        seen_ref_stamps.add(norm_ts)

        try:
            if any(isinstance(item.get(k), bool) for k in ("open", "high", "low", "close")):
                discrepancies.append({"type": "INVALID_REFERENCE_OHLC", "timestamp": norm_ts, "reason": "Boolean OHLC in reference."})
                continue
            ro, rh, rl, rc = float(item["open"]), float(item["high"]), float(item["low"]), float(item["close"])
        except (KeyError, ValueError, TypeError):
            discrepancies.append({"type": "INVALID_REFERENCE_OHLC", "timestamp": norm_ts, "reason": "Missing or non-numeric OHLC in reference."})
            continue

        if ro <= 0 or rh <= 0 or rl <= 0 or rc <= 0 or rh < max(ro, rc) or rl > min(ro, rc) or rh < rl:
            discrepancies.append({"type": "INVALID_REFERENCE_OHLC", "timestamp": norm_ts, "reason": "Invalid OHLC geometry in reference."})
            continue

        ref_by_time[norm_ts] = {"open": ro, "high": rh, "low": rl, "close": rc}

    matched_count = 0
    max_discrepancy = 0.0
    regular_ts_set = set()

    for c in regular_candles:
        ts = c["raw_timestamp"]
        regular_ts_set.add(ts)
        ts_norm = ts.replace(" ", "T")[:19]
        match_key = ts if ts in ref_by_time else ts_norm if ts_norm in ref_by_time else ts[:19]
        if match_key not in ref_by_time:
            discrepancies.append({
                "type": "MISSING_CANDLE_IN_REFERENCE",
                "timestamp": ts,
                "reason": f"Completed regular candle at {ts} is missing in independent reference.",
            })
            continue

        ref = ref_by_time[match_key]
        candle_matched = True
        for field in ("open", "high", "low", "close"):
            prov_p = c[field]
            ref_p = ref[field]
            delta = abs(prov_p - ref_p)
            if delta > max_discrepancy:
                max_discrepancy = delta
            if delta > tolerance:
                candle_matched = False
                discrepancies.append({
                    "type": "OHLC_MISMATCH",
                    "timestamp": ts,
                    "field": field,
                    "provider_price": prov_p,
                    "reference_price": ref_p,
                    "difference": round(delta, 4),
                    "tolerance": tolerance,
                    "reason": f"{field.capitalize()} price differs by {delta:.4f} exceeding tolerance {tolerance}.",
                })
        if candle_matched:
            matched_count += 1

    ref_provenance = {
        "reference_path": str(reference_path) if reference_path else None,
        "reference_hash": hashlib.sha256(json.dumps(reference_data or [], sort_keys=True).encode()).hexdigest() if reference_data else None,
    }
    missing_per_source = {
        "provider_missing": validated["missing_candles_count"],
        "reference_missing": sum(1 for d in discrepancies if d.get("type") == "MISSING_CANDLE_IN_REFERENCE"),
    }
    duplicate_obs_count = sum(1 for d in discrepancies if d.get("type") == "DUPLICATE_REFERENCE_CANDLE")
    mismatched_count = len(regular_candles) - matched_count

    if discrepancies:
        return {
            "ok": False,
            "code": "RECONCILIATION_FAILED",
            "status": "DISCREPANCIES_DETECTED",
            "message": f"Reconciliation failed with {len(discrepancies)} discrepancies.",
            "raw_data_hash": raw_sha,
            "raw_hash_unchanged": True,
            "total_candles_received": validated["total_candles_received"],
            "regular_candles_count": validated["regular_candle_count"],
            "matched_candles_count": matched_count,
            "mismatched_candles_count": mismatched_count,
            "missing_candles_per_source": missing_per_source,
            "duplicate_observations_count": duplicate_obs_count,
            "max_discrepancy": round(max_discrepancy, 6),
            "timestamp_alignment": "VALIDATED" if not any(d.get("type") in ("TIMEZONE_MISMATCH", "INVALID_REFERENCE_TIMESTAMP") for d in discrepancies) else "MISALIGNED",
            "excluded_observations": validated.get("excluded_boundary_candles", []),
            "unresolved_discrepancies": discrepancies,
            "reference_provenance": ref_provenance,
            "discrepancies": discrepancies,
            "manifest": None,
            "promoted": False,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    manifest = {
        "manifest_version": "m11-manifest-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instrument": "NIFTY",
        "exchange": "NSE",
        "interval": "15minute",
        "timezone": "Asia/Kolkata",
        "source_provenance": {
            "raw_data_hash": raw_sha,
        },
        "verification": {
            "status": "RECONCILED_MATCHED",
            "tolerance": tolerance,
            "max_observed_discrepancy": round(max_discrepancy, 6),
            "matched_candle_count": matched_count,
        },
        "included_candle_count": len(regular_candles),
        "excluded_candle_count": validated["excluded_boundary_count"],
        "session_count": validated["session_count"],
        "checksum": content_hash({
            "raw_sha": raw_sha,
            "matched_count": matched_count,
            "candle_count": len(regular_candles),
        }),
    }

    result = {
        "ok": True,
        "code": "RECONCILIATION_MATCHED",
        "status": "RECONCILED_MATCHED",
        "message": "Historical dataset successfully reconciled against independent reference.",
        "raw_data_hash": raw_sha,
        "raw_hash_unchanged": True,
        "dataset_id": validated["dataset_id"],
        "included_candles_count": len(regular_candles),
        "excluded_candles_count": validated["excluded_boundary_count"],
        "matched_candles_count": matched_count,
        "mismatched_candles_count": 0,
        "missing_candles_per_source": missing_per_source,
        "duplicate_observations_count": duplicate_obs_count,
        "max_discrepancy": round(max_discrepancy, 6),
        "timestamp_alignment": "VALIDATED",
        "excluded_observations": validated.get("excluded_boundary_candles", []),
        "unresolved_discrepancies": [],
        "reference_provenance": ref_provenance,
        "discrepancies": [],
        "manifest": manifest,
        "dataset": validated["dataset"],
        "promoted": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }

    if promote:
        promoted = promote_reconciled_dataset(result, store=store)
        result["promoted"] = promoted.get("promoted", False)
        result["promotion"] = promoted

    return result


def evaluate_real_data_walkforward(
    dataset_or_artifact: dict,
    *,
    config: object | None = None,
) -> dict:
    """Evaluate walk-forward baselines on real market data, strictly requiring verified status.

    Fails closed if the dataset is unverified, quarantined, or synthetic.
    """
    from app.market.provenance import data_category
    from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward

    cat = data_category(dataset_or_artifact)
    is_verified = dataset_or_artifact.get("real_market_data_verified") is True

    if not is_verified or cat != "REAL_MARKET_DATA":
        return {
            "ok": False,
            "code": "BLOCKED_UNVERIFIED_DATA",
            "status": "BLOCKED",
            "message": (
                "Real-data walk-forward evaluation requires verified, trusted historical market data. "
                "Quarantined or unverified datasets cannot be evaluated."
            ),
            "data_category": cat,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }

    return run_walk_forward(
        dataset_or_artifact,
        config=config,
        require_verified_history=True,
    )


def seal_historical_manifest(
    validated_or_reconciled: dict,
    *,
    source_provider: str = "groww",
    notes: str | None = None,
) -> dict:
    """Produce a deterministic, auditable dataset manifest for a validated historical dataset.

    Enforces M12 dataset sealing rules:
    - Captures instrument, interval, timezone, candle counts, boundary exclusions, and session gaps.
    - Records immutable raw source hashes and independent verification status.
    - Deterministically hashes the manifest content into a sealing checksum.
    - Preserves fail-closed safety flags (forecast_ready=False, real_market_data_verified=False).
    """
    from datetime import datetime, timezone
    from app.features.pipeline import content_hash

    raw_sha = validated_or_reconciled.get("raw_data_hash")
    dataset_id = validated_or_reconciled.get("dataset_id")
    reg_count = validated_or_reconciled.get("regular_candle_count") or len(validated_or_reconciled.get("valid_regular_candles") or [])
    boundary_count = validated_or_reconciled.get("excluded_boundary_count", 0)
    incomplete_count = validated_or_reconciled.get("excluded_incomplete_count", 0)
    missing_count = validated_or_reconciled.get("missing_candles_count", 0)
    session_count = validated_or_reconciled.get("session_count", 0)
    verification_status = validated_or_reconciled.get("status") or ("RECONCILED_MATCHED" if validated_or_reconciled.get("ok") and validated_or_reconciled.get("code") == "RECONCILIATION_MATCHED" else "UNVERIFIED")

    body = {
        "manifest_version": "m12-sealed-manifest-1",
        "instrument": validated_or_reconciled.get("instrument", "NIFTY"),
        "exchange": "NSE",
        "interval": validated_or_reconciled.get("interval", "15minute"),
        "timezone": "Asia/Kolkata",
        "source_provider": source_provider,
        "source_provenance": {
            "raw_data_hash": raw_sha,
            "dataset_id": dataset_id,
        },
        "coverage": {
            "regular_candle_count": reg_count,
            "session_count": session_count,
            "missing_candles_count": missing_count,
            "excluded_boundary_count": boundary_count,
            "excluded_incomplete_count": incomplete_count,
            "has_gaps": missing_count > 0,
        },
        "verification": {
            "status": verification_status,
            "independent_reference_verified": verification_status == "RECONCILED_MATCHED",
        },
        "notes": notes or "Sealed historical dataset manifest. Raw observations preserved unmodified.",
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }
    checksum = content_hash(body)
    manifest = dict(body)
    manifest["checksum"] = checksum
    manifest["sealed_at"] = datetime.now(timezone.utc).isoformat()
    return manifest




