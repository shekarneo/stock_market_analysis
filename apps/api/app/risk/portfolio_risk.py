"""Milestone M31: Portfolio Risk Management, Volatility-Parity Sizing, and Intraday Square-Off Safeguards.

Prepared strictly for research and financial loss-prevention verification.
Live trading, paper trading, and forecast approval are strictly disabled.
All safety invariants remain hardcoded to False.

Core Objectives:
1. Volatility-Parity Position Sizing:
   Normalize dollar risk across different market volatility regimes using ATR.
   High-volatility regimes receive smaller exposure; low-volatility regimes receive larger exposure.
2. Fractional Half-Kelly Capital Allocation:
   Sizes capital dynamically based on model conviction, win probability p, and payoff ratio b.
   Clamped to maximum 2.0% risk budget per trade. Vetoes trades when Kelly <= 0.
3. Indian Exchange Intraday Square-Off Safeguards:
   - 09:15 to 15:10 IST: Normal entry/exit permitted.
   - 15:10 to 15:15 IST: ENTRY_CUTOFF (New entry orders blocked).
   - 15:15 to 15:25 IST: MANDATORY_SQUARE_OFF (All intraday positions forced to Cash).
   - 15:30+ IST: MARKET_CLOSED.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time
from decimal import Decimal
import logging
import math
from typing import Any
from zoneinfo import ZoneInfo

from app.instrument_specs import INSTRUMENT_SPECS, lot_size_for
from app.risk.money import decimal_or_none
from app.settings import REPO_ROOT

log = logging.getLogger("imm.risk.portfolio")
ASIA_KOLKATA = ZoneInfo("Asia/Kolkata")

# Lot sizes for tradable underlyings, derived from the instrument master (app/instrument_specs.py)
INDIAN_LOT_SIZES: dict[str, int] = {
    inst: spec.lot_size for inst, spec in INSTRUMENT_SPECS.items() if spec.lot_size is not None
}

# Maximum permissible risk fraction of total capital per individual trade
MAX_TRADE_RISK_FRACTION = Decimal("0.02")  # 2.0%
# Hard portfolio-level daily loss cap
PORTFOLIO_DAILY_LOSS_CAP = Decimal("0.05")  # 5.0%


@dataclass
class VolatilityParitySizeResult:
    instrument: str
    decision: str                # "EXECUTE" or "NO_TRADE"
    recommended_lots: int
    total_quantity: int
    capital_allocated_inr: float
    dollar_risk_at_stop_inr: float
    atr_used: float
    kelly_fraction: float
    reasons: list[str]
    forecast_ready: bool = False
    paper_approved: bool = False
    live_approved: bool = False
    real_market_data_verified: bool = False


@dataclass
class SquareOffAssessment:
    current_time_ist: str
    status: str                  # "NORMAL_TRADING", "ENTRY_CUTOFF", "MANDATORY_SQUARE_OFF", "MARKET_CLOSED"
    allow_new_entries: bool
    force_square_off_now: bool
    seconds_to_square_off: int
    reasons: list[str]


# ==============================================================================
# 1. VOLATILITY-PARITY & FRACTIONAL HALF-KELLY POSITION SIZING
# ==============================================================================

def calculate_volatility_parity_size(
    *,
    instrument: str,
    total_capital_inr: float | Decimal,
    entry_price: float | Decimal,
    stop_loss_price: float | Decimal,
    atr_value: float | Decimal,
    win_probability: float = 0.50,
    reward_to_risk_ratio: float = 1.5,
    max_risk_fraction: float | Decimal = MAX_TRADE_RISK_FRACTION,
    custom_lot_size: int | None = None,
) -> VolatilityParitySizeResult:
    """Calculate position size targeting equal dollar volatility risk across trades.
    
    Formula:
      1. Half-Kelly fraction: f* = 0.5 * [(b*p - (1-p)) / b]
         Clamped to [0.0, max_risk_fraction].
      2. Dollar Risk Budget = Total Capital * f*
      3. Per-Unit Risk = max(abs(Entry - StopLoss), ATR * 1.5)
      4. Target Units = Dollar Risk Budget / Per-Unit Risk
      5. Lot Count = floor(Target Units / LotSize)
    """
    reasons: list[str] = []

    cap_dec = decimal_or_none(total_capital_inr)
    entry_dec = decimal_or_none(entry_price)
    stop_dec = decimal_or_none(stop_loss_price)
    atr_dec = decimal_or_none(atr_value)
    max_risk_dec = decimal_or_none(max_risk_fraction) or MAX_TRADE_RISK_FRACTION

    if cap_dec is None or cap_dec <= Decimal("0"):
        reasons.append("INVALID_TOTAL_CAPITAL")
    if entry_dec is None or entry_dec <= Decimal("0"):
        reasons.append("INVALID_ENTRY_PRICE")
    if stop_dec is None or stop_dec <= Decimal("0"):
        reasons.append("INVALID_STOP_LOSS_PRICE")
    if atr_dec is None or atr_dec <= Decimal("0"):
        reasons.append("INVALID_ATR_VALUE")

    lot_size = custom_lot_size or lot_size_for(instrument)
    if lot_size is None or lot_size <= 0:
        reasons.append("INVALID_LOT_SIZE")

    if reasons:
        return VolatilityParitySizeResult(
            instrument=instrument,
            decision="NO_TRADE",
            recommended_lots=0,
            total_quantity=0,
            capital_allocated_inr=0.0,
            dollar_risk_at_stop_inr=0.0,
            atr_used=float(atr_dec or 0.0),
            kelly_fraction=0.0,
            reasons=reasons,
        )

    # 1. Fractional Half-Kelly calculation
    p = win_probability
    b = max(reward_to_risk_ratio, 0.1)
    # Full Kelly: (b*p - q) / b where q = 1 - p
    full_kelly = (b * p - (1.0 - p)) / b
    half_kelly = max(0.0, full_kelly * 0.5)

    # Clamp Kelly fraction to maximum risk budget
    risk_fraction = min(Decimal(str(round(half_kelly, 6))), max_risk_dec)

    if risk_fraction <= Decimal("0"):
        reasons.append("KELLY_VETO_NON_POSITIVE_EDGE")
        return VolatilityParitySizeResult(
            instrument=instrument,
            decision="NO_TRADE",
            recommended_lots=0,
            total_quantity=0,
            capital_allocated_inr=0.0,
            dollar_risk_at_stop_inr=0.0,
            atr_used=float(atr_dec),
            kelly_fraction=float(half_kelly),
            reasons=reasons,
        )

    # 2. Risk budget in INR
    dollar_risk_budget = cap_dec * risk_fraction

    # 3. Per-share risk: distance from entry to stop, padded by ATR volatility floor
    price_diff = abs(entry_dec - stop_dec)
    vol_floor = atr_dec * Decimal("1.0")
    per_share_risk = max(price_diff, vol_floor)

    if per_share_risk <= Decimal("0"):
        reasons.append("ZERO_PER_SHARE_RISK")
        return VolatilityParitySizeResult(
            instrument=instrument,
            decision="NO_TRADE",
            recommended_lots=0,
            total_quantity=0,
            capital_allocated_inr=0.0,
            dollar_risk_at_stop_inr=0.0,
            atr_used=float(atr_dec),
            kelly_fraction=float(half_kelly),
            reasons=reasons,
        )

    # 4. Target shares and discrete lot allocation
    target_shares = dollar_risk_budget / per_share_risk
    lot_count = int(math.floor(float(target_shares) / float(lot_size)))

    if lot_count < 1:
        reasons.append("BUDGET_BELOW_MINIMUM_LOT_SIZE")
        return VolatilityParitySizeResult(
            instrument=instrument,
            decision="NO_TRADE",
            recommended_lots=0,
            total_quantity=0,
            capital_allocated_inr=0.0,
            dollar_risk_at_stop_inr=0.0,
            atr_used=float(atr_dec),
            kelly_fraction=float(half_kelly),
            reasons=reasons,
        )

    total_qty = lot_count * lot_size
    allocated_capital = float(Decimal(total_qty) * entry_dec)
    total_dollar_risk = float(Decimal(total_qty) * per_share_risk)

    return VolatilityParitySizeResult(
        instrument=instrument,
        decision="EXECUTE",
        recommended_lots=lot_count,
        total_quantity=total_qty,
        capital_allocated_inr=allocated_capital,
        dollar_risk_at_stop_inr=total_dollar_risk,
        atr_used=float(atr_dec),
        kelly_fraction=float(half_kelly),
        reasons=["POSITION_SIZED_WITHIN_RISK_LIMITS"],
    )


# ==============================================================================
# 2. INTRADAY EXCHANGE SQUARE-OFF SAFEGUARDS
# ==============================================================================

def assess_intraday_square_off(
    current_time: datetime | str,
) -> SquareOffAssessment:
    """Assess whether current IST time allows new entries or mandates intraday square-off.
    
    Indian Market Hours Timeline:
    - 09:15 to 15:10 IST: NORMAL_TRADING (New entries allowed, exits allowed)
    - 15:10 to 15:15 IST: ENTRY_CUTOFF (New entry orders blocked to prevent tail exposure)
    - 15:15 to 15:25 IST: MANDATORY_SQUARE_OFF (All intraday positions forced to close)
    - 15:30+ IST:         MARKET_CLOSED
    """
    reasons: list[str] = []

    if isinstance(current_time, str):
        # Format HH:MM:SS or ISO
        cleaned = current_time.strip()
        if "T" in cleaned or " " in cleaned:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ASIA_KOLKATA)
            else:
                dt = dt.astimezone(ASIA_KOLKATA)
            t_obj = dt.time()
        else:
            parts = cleaned.split(":")
            t_obj = time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    elif isinstance(current_time, datetime):
        if current_time.tzinfo is None:
            dt = current_time.replace(tzinfo=ASIA_KOLKATA)
        else:
            dt = current_time.astimezone(ASIA_KOLKATA)
        t_obj = dt.time()
    else:
        raise ValueError(f"Unsupported time format: {current_time!r}")

    t_str = t_obj.strftime("%H:%M:%S")

    # Time boundaries in seconds from midnight
    cur_secs = t_obj.hour * 3600 + t_obj.minute * 60 + t_obj.second
    market_open_secs = 9 * 3600 + 15 * 60       # 09:15:00
    entry_cutoff_secs = 15 * 3600 + 10 * 60     # 15:10:00
    square_off_secs = 15 * 3600 + 15 * 60       # 15:15:00
    market_close_secs = 15 * 3600 + 30 * 60     # 15:30:00

    seconds_to_sqoff = square_off_secs - cur_secs

    if cur_secs < market_open_secs:
        status = "MARKET_CLOSED"
        allow_entries = False
        force_sqoff = False
        reasons.append("Market is pre-open (prior to 09:15 IST)")
    elif market_open_secs <= cur_secs < entry_cutoff_secs:
        status = "NORMAL_TRADING"
        allow_entries = True
        force_sqoff = False
        reasons.append("Normal trading session active")
    elif entry_cutoff_secs <= cur_secs < square_off_secs:
        status = "ENTRY_CUTOFF"
        allow_entries = False
        force_sqoff = False
        reasons.append("Entry cutoff active: <5 minutes to intraday square-off window")
    elif square_off_secs <= cur_secs <= market_close_secs:
        status = "MANDATORY_SQUARE_OFF"
        allow_entries = False
        force_sqoff = True
        reasons.append("Mandatory intraday square-off window active (15:15-15:30 IST)")
    else:
        status = "MARKET_CLOSED"
        allow_entries = False
        force_sqoff = False
        reasons.append("Market session concluded (after 15:30 IST)")

    return SquareOffAssessment(
        current_time_ist=t_str,
        status=status,
        allow_new_entries=allow_entries,
        force_square_off_now=force_sqoff,
        seconds_to_square_off=max(0, seconds_to_sqoff),
        reasons=reasons,
    )
