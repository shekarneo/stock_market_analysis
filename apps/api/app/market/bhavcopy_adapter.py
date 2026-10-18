"""Milestone M29: Official NSE Bhavcopy Secondary Provider Adapter & Multi-Provider Reconciliation.

Prepared strictly for research and market-data integrity verification.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Provide an independent secondary provider adapter for official daily Bhavcopy files
   from the National Stock Exchange of India (NSE).
2. Support both NSE Capital Market (Equity) Bhavcopy and NSE Index Daily Reports (ind_close_all_*.csv).
3. Daily Session Aggregation & Cross-Reconciliation:
   - Resample primary provider (Groww) 15m intraday candles into daily session bars.
   - Reconcile bar-by-bar against official NSE Bhavcopy for corresponding calendar dates.
   - Compute discrepancies in basis points (bps) for Open, High, Low, Close.
   - Enforce strict 5.0 bps (0.05%) acceptance tolerance.
   - Record conflicting records into PostgreSQL `CandleConflictAudit` table.
4. Foundation for setting `real_market_data_verified = True` once independent corroboration passes.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.domain.tables import CandleConflictAudit, MarketCandle, RawResponseArtifact, utcnow
from app.settings import REPO_ROOT

log = logging.getLogger("imm.market.bhavcopy")
ASIA_KOLKATA = ZoneInfo("Asia/Kolkata")

# Strict tolerance for cross-broker/exchange price discrepancy: 5 basis points (0.05%)
BHAVCOPY_TOLERANCE_BPS = 5.0


@dataclass
class DailyBhavcopyRecord:
    symbol: str
    date_str: str          # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover_inr: float
    source: str = "NSE_BHAVCOPY"


@dataclass
class DailyReconciliationMatch:
    date_str: str
    symbol: str
    groww_open: float
    groww_high: float
    groww_low: float
    groww_close: float
    groww_volume: float
    nse_open: float
    nse_high: float
    nse_low: float
    nse_close: float
    nse_volume: float
    diff_open_bps: float
    diff_high_bps: float
    diff_low_bps: float
    diff_close_bps: float
    max_diff_bps: float
    is_match: bool
    status: str            # "RECONCILED_MATCH" or "CONFLICT_DETECTED"
    reason: str


@dataclass
class BhavcopyVerificationReport:
    symbol: str
    dataset_id: str
    total_days_evaluated: int
    matched_days_count: int
    conflict_days_count: int
    tolerance_bps: float
    mean_close_diff_bps: float
    max_discrepancy_bps: float
    verification_level: str       # "LEVEL_3_INDEPENDENT_CORROBORATION"
    verification_status: str      # "VERIFIED_MATCH" or "CONFLICT_FLAGGED"
    matches: list[DailyReconciliationMatch]
    safety_invariants: dict[str, bool]
    timestamp: str


# ==============================================================================
# 1. OFFICIAL NSE BHAVCOPY PARSERS
# ==============================================================================

def parse_nse_index_bhavcopy_csv(csv_text: str, target_index: str = "Nifty 50") -> list[DailyBhavcopyRecord]:
    """Parse official NSE Index Daily Closing CSV (e.g. ind_close_all_*.csv).
    
    Expected Headers:
    Index Name, Index Date, Open Index Value, High Index Value, Low Index Value,
    Closing Index Value, Points Change, Change(%), Volume, Turnover (Rs. Cr.), P/E, P/B, Div Yield
    """
    records: list[DailyBhavcopyRecord] = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))

    for raw_row in reader:
        # Strip whitespace from keys and values
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}
        idx_name = row.get("Index Name", "")

        # Normalize index name match
        if idx_name.lower().replace(" ", "") == target_index.lower().replace(" ", ""):
            # Parse date format: usually DD-MM-YYYY or YYYY-MM-DD
            raw_date = row.get("Index Date", "")
            parsed_date = _parse_date_string(raw_date)

            o = float(row.get("Open Index Value", "0").replace(",", "") or 0.0)
            h = float(row.get("High Index Value", "0").replace(",", "") or 0.0)
            l = float(row.get("Low Index Value", "0").replace(",", "") or 0.0)
            c = float(row.get("Closing Index Value", "0").replace(",", "") or 0.0)
            v = float(row.get("Volume", "0").replace(",", "") or 0.0)
            turnover_cr = float(row.get("Turnover (Rs. Cr.)", "0").replace(",", "") or 0.0)
            turnover_inr = turnover_cr * 10000000.0

            assert h >= l, f"High {h} < Low {l} in NSE Bhavcopy for {parsed_date}"
            assert h >= max(o, c) - 1e-4, f"High lower than open/close for {parsed_date}"
            assert l <= min(o, c) + 1e-4, f"Low higher than open/close for {parsed_date}"

            records.append(
                DailyBhavcopyRecord(
                    symbol="NIFTY",
                    date_str=parsed_date,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                    turnover_inr=turnover_inr,
                    source="NSE_INDEX_BHAVCOPY",
                )
            )

    return records


def parse_nse_cm_equity_bhavcopy_csv(csv_text: str, target_symbol: str) -> list[DailyBhavcopyRecord]:
    """Parse official NSE Capital Market (CM) Equity Bhavcopy CSV.
    
    Expected Headers:
    SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY, TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN
    """
    records: list[DailyBhavcopyRecord] = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))

    for raw_row in reader:
        row = {k.strip(): v.strip() for k, v in raw_row.items() if k}
        sym = row.get("SYMBOL", "").upper()
        series = row.get("SERIES", "").upper()

        if sym == target_symbol.upper() and series in {"EQ", "IN"}:
            raw_date = row.get("TIMESTAMP", "")
            parsed_date = _parse_date_string(raw_date)

            o = float(row.get("OPEN", "0").replace(",", "") or 0.0)
            h = float(row.get("HIGH", "0").replace(",", "") or 0.0)
            l = float(row.get("LOW", "0").replace(",", "") or 0.0)
            c = float(row.get("CLOSE", "0").replace(",", "") or 0.0)
            v = float(row.get("TOTTRDQTY", "0").replace(",", "") or 0.0)
            turnover_inr = float(row.get("TOTTRDVAL", "0").replace(",", "") or 0.0)

            records.append(
                DailyBhavcopyRecord(
                    symbol=sym,
                    date_str=parsed_date,
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                    turnover_inr=turnover_inr,
                    source="NSE_CM_EQUITY_BHAVCOPY",
                )
            )

    return records


def _parse_date_string(d_str: str) -> str:
    """Normalize various date strings ('DD-MM-YYYY', 'DD-Mon-YYYY', 'YYYY-MM-DD') into 'YYYY-MM-DD'."""
    d_clean = d_str.strip()
    # Check for DD-Mon-YYYY (e.g., 14-OCT-2026)
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(d_clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return d_clean[:10]


# ==============================================================================
# 2. GROWW 15M CANDLE AGGREGATOR TO DAILY SESSIONS
# ==============================================================================

def aggregate_groww_candles_to_daily(raw_15m_candles: list[list[Any]]) -> dict[str, dict[str, float]]:
    """Aggregate continuous 15m Groww candles into daily session OHLCV.
    
    Session rules for Indian equity markets:
    - Daily Open: Open of first 15m candle (09:15:00).
    - Daily High: Maximum High across all 15m candles in the day.
    - Daily Low: Minimum Low across all 15m candles in the day.
    - Daily Close: Close of last 15m candle (15:15:00).
    - Daily Volume: Sum of volumes across all 15m candles.
    """
    days: dict[str, list[list[Any]]] = {}

    for c in raw_15m_candles:
        ts_str = str(c[0])
        date_str = ts_str[:10]
        if date_str not in days:
            days[date_str] = []
        days[date_str].append(c)

    daily_sessions: dict[str, dict[str, float]] = {}

    for date_str, c_list in sorted(days.items()):
        if not c_list:
            continue
        first_bar = c_list[0]
        last_bar = c_list[-1]

        d_open = float(first_bar[1])
        d_high = max(float(x[2]) for x in c_list)
        d_low = min(float(x[3]) for x in c_list)
        d_close = float(last_bar[4])
        d_vol = sum(float(x[5]) for x in c_list)

        daily_sessions[date_str] = {
            "open": d_open,
            "high": d_high,
            "low": d_low,
            "close": d_close,
            "volume": d_vol,
            "bar_count": len(c_list),
        }

    return daily_sessions


# ==============================================================================
# 3. MULTI-PROVIDER RECONCILIATION & CONFLICT AUDITING
# ==============================================================================

def reconcile_groww_with_bhavcopy(
    groww_15m_candles: list[list[Any]],
    bhavcopy_records: list[DailyBhavcopyRecord],
    dataset_id: str,
    tolerance_bps: float = BHAVCOPY_TOLERANCE_BPS,
    db_session: Session | None = None,
) -> BhavcopyVerificationReport:
    """Reconcile Groww historical candles bar-by-bar against official NSE Bhavcopy.
    
    Logs any discrepancy exceeding tolerance_bps into PostgreSQL CandleConflictAudit.
    """
    groww_daily = aggregate_groww_candles_to_daily(groww_15m_candles)
    bhav_map = {r.date_str: r for r in bhavcopy_records}

    matches: list[DailyReconciliationMatch] = []
    conflict_count = 0
    matched_count = 0
    max_discrepancy = 0.0
    close_diffs = []

    for d_str, g_data in sorted(groww_daily.items()):
        if d_str not in bhav_map:
            continue

        b_data = bhav_map[d_str]

        # Discrepancies in basis points: |g - b| / b * 10000
        d_o_bps = abs(g_data["open"] - b_data.open) / (b_data.open + 1e-6) * 10000.0
        d_h_bps = abs(g_data["high"] - b_data.high) / (b_data.high + 1e-6) * 10000.0
        d_l_bps = abs(g_data["low"] - b_data.low) / (b_data.low + 1e-6) * 10000.0
        d_c_bps = abs(g_data["close"] - b_data.close) / (b_data.close + 1e-6) * 10000.0

        max_day_diff = max(d_o_bps, d_h_bps, d_l_bps, d_c_bps)
        max_discrepancy = max(max_discrepancy, max_day_diff)
        close_diffs.append(d_c_bps)

        is_match = max_day_diff <= tolerance_bps

        if is_match:
            matched_count += 1
            status = "RECONCILED_MATCH"
            reason = f"Max discrepancy {max_day_diff:.2f} bps within {tolerance_bps:.1f} bps tolerance"
        else:
            conflict_count += 1
            status = "CONFLICT_DETECTED"
            reason = (
                f"Discrepancy {max_day_diff:.2f} bps exceeds {tolerance_bps:.1f} bps tolerance. "
                f"(Open: {d_o_bps:.2f} bps, High: {d_h_bps:.2f} bps, Low: {d_l_bps:.2f} bps, Close: {d_c_bps:.2f} bps)"
            )

            # Record conflict in DB if session is available
            if db_session is not None:
                audit_record = CandleConflictAudit(
                    symbol="NIFTY",
                    interval="1day",
                    timestamp=datetime.strptime(f"{d_str} 15:30:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=ASIA_KOLKATA),
                    existing_ohlcv={
                        "open": g_data["open"],
                        "high": g_data["high"],
                        "low": g_data["low"],
                        "close": g_data["close"],
                        "volume": g_data["volume"],
                        "source": "Groww_15m_Aggregated",
                    },
                    incoming_ohlcv={
                        "open": b_data.open,
                        "high": b_data.high,
                        "low": b_data.low,
                        "close": b_data.close,
                        "volume": b_data.volume,
                        "source": b_data.source,
                    },
                    resolution="FLAGGED_FOR_HUMAN_AUDIT",
                    reason=reason,
                    incoming_artifact_id=f"bhavcopy_{d_str}",
                    created_at=utcnow(),
                )
                db_session.add(audit_record)

        matches.append(
            DailyReconciliationMatch(
                date_str=d_str,
                symbol="NIFTY",
                groww_open=g_data["open"],
                groww_high=g_data["high"],
                groww_low=g_data["low"],
                groww_close=g_data["close"],
                groww_volume=g_data["volume"],
                nse_open=b_data.open,
                nse_high=b_data.high,
                nse_low=b_data.low,
                nse_close=b_data.close,
                nse_volume=b_data.volume,
                diff_open_bps=d_o_bps,
                diff_high_bps=d_h_bps,
                diff_low_bps=d_l_bps,
                diff_close_bps=d_c_bps,
                max_diff_bps=max_day_diff,
                is_match=is_match,
                status=status,
                reason=reason,
            )
        )

    total_evaluated = len(matches)
    mean_close_diff = float(sum(close_diffs) / len(close_diffs)) if close_diffs else 0.0

    verif_status = "VERIFIED_MATCH" if conflict_count == 0 and total_evaluated > 0 else "CONFLICT_FLAGGED"

    report = BhavcopyVerificationReport(
        symbol="NIFTY",
        dataset_id=dataset_id,
        total_days_evaluated=total_evaluated,
        matched_days_count=matched_count,
        conflict_days_count=conflict_count,
        tolerance_bps=tolerance_bps,
        mean_close_diff_bps=mean_close_diff,
        max_discrepancy_bps=max_discrepancy,
        verification_level="LEVEL_3_INDEPENDENT_CORROBORATION",
        verification_status=verif_status,
        matches=matches,
        safety_invariants={
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return report


def save_bhavcopy_raw_artifact(raw_content: str, date_str: str) -> Path:
    """Save raw Bhavcopy CSV into immutable var/history/bhavcopy/ directory with SHA-256 hash."""
    out_dir = REPO_ROOT / "var" / "history" / "bhavcopy"
    out_dir.mkdir(parents=True, exist_ok=True)

    sha256 = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    out_file = out_dir / f"nse_bhavcopy_{date_str}_{sha256[:16]}.csv"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(raw_content)

    log.info(f"Saved raw Bhavcopy artifact to {out_file} (SHA256: {sha256})")
    return out_file
