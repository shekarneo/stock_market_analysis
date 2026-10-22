"""Groww Option Chain service, expiry validator, and observation builder.

Integrates the official Groww GET /v1/option-chain endpoint.
Validates underlying LTP, strikes, CE/PE contracts, open interest, and Greeks.
Adheres strictly to Truth in Data: missing or null values are never replaced with zero.
Persists normalized snapshot atomically and produces Stage 10 DERIVATIVES observations.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.integrations.groww import (
    normalize_option_chain_response,
    read_option_chain,
)
from app.integrations.http import HttpxCaller
from app.integrations.service import groww_read_token
from app.settings import REPO_ROOT, Settings

OPTION_CHAIN_STORE_PATH = REPO_ROOT / "var" / "market" / "live_reads" / "option_chain_latest.json"

# Canonical active listed NIFTY FNO expiries extracted from official Groww instrument master
CANONICAL_NIFTY_EXPIRIES: tuple[str, ...] = (
    "2026-10-19",
    "2026-10-27",
    "2026-11-03",
    "2026-11-09",
    "2026-11-17",
    "2026-11-23",
    "2026-12-29",
    "2027-03-30",
    "2027-06-29",
    "2027-09-28",
    "2027-12-28",
    "2028-06-27",
    "2028-12-26",
    "2029-06-26",
    "2029-12-24",
    "2030-06-25",
    "2030-12-31",
    "2031-06-24",
)

ACTIVE_NIFTY_EXPIRIES = CANONICAL_NIFTY_EXPIRIES
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_contract_expiry(
    expiry_date: str,
    as_of: date | None = None,
    allowed_expiries: tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    """Validate contract expiry against date format, currency calendar, and exchange master.

    Returns:
        (is_valid, reason_code)
    """
    if not isinstance(expiry_date, str) or not _ISO_DATE_PATTERN.match(expiry_date):
        return False, "MALFORMED_EXPIRY"

    try:
        exp_d = date.fromisoformat(expiry_date)
    except ValueError:
        return False, "INVALID_CALENDAR_DATE"

    ref_date = as_of or datetime.now(timezone.utc).date()
    if exp_d < ref_date:
        return False, "EXPIRED_CONTRACT"

    allowed = allowed_expiries if allowed_expiries is not None else CANONICAL_NIFTY_EXPIRIES
    if allowed and expiry_date not in allowed:
        return False, "UNLISTED_CONTRACT_EXPIRY"

    return True, "VALID"


def resolve_upcoming_expiry(underlying: str = "NIFTY", as_of: date | None = None) -> str:
    """Find the nearest valid contract expiry >= as_of date from canonical master."""
    ref_date = as_of or datetime.now(timezone.utc).date()
    ref_iso = ref_date.isoformat()
    for exp in CANONICAL_NIFTY_EXPIRIES:
        if exp >= ref_iso:
            return exp
    return CANONICAL_NIFTY_EXPIRIES[-1]


def fetch_groww_option_chain(
    session: Any,
    settings: Settings,
    *,
    caller: Any = None,
    underlying: str = "NIFTY",
    exchange: str = "NSE",
    expiry_date: str | None = None,
    retrieved_at: datetime | None = None,
    path: Path | None = None,
) -> dict:
    """Fetch live option chain from Groww, validate, compute metrics, and persist snapshot."""
    ret_dt = retrieved_at or datetime.now(timezone.utc)
    if ret_dt.tzinfo is None:
        ret_dt = ret_dt.replace(tzinfo=timezone.utc)

    if expiry_date:
        valid, reason = validate_contract_expiry(expiry_date, as_of=ret_dt.date())
        if not valid:
            return {
                "ok": False,
                "code": reason,
                "message": f"Contract expiry {expiry_date} is invalid ({reason}).",
                "observation": None,
            }
        resolved_expiry = expiry_date
    else:
        resolved_expiry = resolve_upcoming_expiry(underlying, ret_dt.date())

    http_caller = caller or HttpxCaller()

    try:
        token = groww_read_token(session, settings, caller=http_caller)
    except Exception as exc:
        return {
            "ok": False,
            "code": "AUTHENTICATION_FAILED",
            "message": f"Could not acquire Groww access token: {exc}",
            "observation": None,
        }

    try:
        http_result = read_option_chain(
            http_caller,
            token,
            exchange=exchange,
            underlying=underlying,
            expiry_date=resolved_expiry,
        )
    except Exception as exc:
        return {
            "ok": False,
            "code": "PROVIDER_ERROR",
            "message": f"Option chain request failed: {exc}",
            "observation": None,
        }

    norm = normalize_option_chain_response(http_result, underlying, resolved_expiry, ret_dt)
    if not norm.get("ok"):
        return norm

    # Atomic persistence of the normalized snapshot and observation
    target_path = path or OPTION_CHAIN_STORE_PATH
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        store_payload = {
            "provider": "groww",
            "status": "SUCCESS",
            "retrieved_at": ret_dt.isoformat(),
            "provider_observed_at": norm["observation"].get("provider_observed_at"),
            "underlying": underlying,
            "exchange": exchange,
            "expiry_date": resolved_expiry,
            "underlying_ltp": norm["underlying_ltp"],
            "strike_count": norm["strike_count"],
            "pcr_oi": norm["pcr_oi"],
            "pcr_volume": norm["pcr_volume"],
            "atm_strike": norm["atm_strike"],
            "atm_iv": norm["atm_iv"],
            "max_pain_strike": norm["max_pain_strike"],
            "total_ce_oi": norm["total_ce_oi"],
            "total_pe_oi": norm["total_pe_oi"],
            "raw_hash": norm["raw_hash"],
            "raw_payload_sha256": norm["raw_hash"],
            "validation_results": norm.get("validation_results"),
            "observation": norm["observation"],
            "strikes": norm.get("strikes", {}),
        }
        tmp = target_path.with_suffix(".tmp")
        content = json.dumps(store_payload, separators=(",", ":"), sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(target_path)
    except Exception:
        pass

    return norm


def load_stored_option_chain_observation(
    path: Path | None = None,
    *,
    as_of: datetime | None = None,
    max_age_seconds: float | None = None,
    enforce_valid_contract: bool = True,
    allow_closed_session: bool = False,
) -> dict | None:
    """Load latest stored DERIVATIVES observation from disk with freshness and validity guards.

    Prevents stale-file reuse after failed provider requests or contract expiry.
    """
    target_path = path or OPTION_CHAIN_STORE_PATH
    if not target_path.is_file():
        return None
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
        if data.get("status") != "SUCCESS":
            return None

        ret_iso = data.get("retrieved_at")
        if not ret_iso:
            return None

        ret_dt = datetime.fromisoformat(ret_iso)
        if ret_dt.tzinfo is None:
            ret_dt = ret_dt.replace(tzinfo=timezone.utc)

        current_time = as_of or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        # 1. Guard against expired contracts in stored snapshot
        expiry_str = data.get("expiry_date")
        if enforce_valid_contract and expiry_str:
            try:
                exp_date = date.fromisoformat(expiry_str)
                if exp_date < current_time.date():
                    return None  # Stored observation is from an expired contract
            except ValueError:
                return None

        # 2. Guard against stale-file reuse
        if max_age_seconds is not None:
            age = (current_time - ret_dt).total_seconds()
            if age > max_age_seconds:
                if allow_closed_session:
                    # Check if market is closed; if closed and within 5 days, allowable as closed session
                    try:
                        from app.market.session_intelligence import MarketState, assess_market_session
                        sess = assess_market_session(data.get("underlying") or "NIFTY", current_time)
                        if sess.market_state in (MarketState.CLOSED, MarketState.POST_CLOSE) and age <= 432000:
                            pass
                        else:
                            return None
                    except Exception:
                        return None
                else:
                    return None

        obs = data.get("observation")
        if isinstance(obs, dict) and obs.get("category") == "DERIVATIVES":
            return obs
    except Exception:
        return None
    return None


def load_stored_option_chain_data(path: Path | None = None) -> dict | None:
    """Load the full stored option chain data structure from disk."""
    target_path = path or OPTION_CHAIN_STORE_PATH
    if not target_path.is_file():
        return None
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
        if data.get("status") == "SUCCESS" and "strikes" in data:
            return data
    except Exception:
        return None
    return None


# Premiums older than this are not treated as live quotes for entries, targets or hit scoring.
MAX_OPTION_QUOTE_AGE_SECONDS = 900

_IST = timezone(timedelta(hours=5, minutes=30))


def get_live_option_quote(
    contract_str: str,
    path: Path | None = None,
    *,
    current_time: datetime | None = None,
    max_age_seconds: int = MAX_OPTION_QUOTE_AGE_SECONDS,
) -> dict | None:
    """Lookup actual live Groww LTP, Greeks, and contract symbol for an option contract.

    Returns dict with ltp, delta, iv, trading_symbol, open_interest, volume, expiry_date, underlying_ltp
    or None if the quote is not found, belongs to another underlying, is for an expired
    contract, or is older than max_age_seconds.
    """
    m = re.search(r"(\d+(?:\.\d+)?)\s*(CE|PE)", str(contract_str), re.IGNORECASE)
    if not m:
        return None
    strike_val = float(m.group(1))
    opt_type = m.group(2).upper()
    data = load_stored_option_chain_data(path)
    if not data:
        return None

    # The stored chain is a single snapshot for one underlying; never serve it for another.
    requested = re.match(r"\s*([A-Za-z]+)", str(contract_str))
    chain_underlying = str(data.get("underlying") or "").upper()
    if requested and chain_underlying and requested.group(1).upper() != chain_underlying:
        return None

    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    expiry_str = data.get("expiry_date")
    if expiry_str:
        try:
            if date.fromisoformat(expiry_str) < now.astimezone(_IST).date():
                return None
        except ValueError:
            return None
    try:
        retrieved = datetime.fromisoformat(str(data.get("retrieved_at")))
    except (TypeError, ValueError):
        return None
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    if (now - retrieved).total_seconds() > max_age_seconds:
        return None

    strikes = data.get("strikes", {})
    strike_data = (
        strikes.get(str(strike_val))
        or strikes.get(f"{strike_val:.1f}")
        or strikes.get(int(strike_val) if strike_val.is_integer() else strike_val)
        or strikes.get(strike_val)
    )
    if not strike_data or not isinstance(strike_data, dict):
        return None
    quote = strike_data.get(opt_type)
    if not quote or not isinstance(quote, dict):
        return None
    ltp = quote.get("ltp")
    if ltp is None or float(ltp) <= 0:
        return None
    greeks = quote.get("greeks") or {}
    delta = greeks.get("delta")
    return {
        "ltp": float(ltp),
        "delta": abs(float(delta)) if delta is not None else None,
        "iv": float(greeks.get("iv")) if greeks.get("iv") is not None else None,
        "trading_symbol": quote.get("trading_symbol"),
        "open_interest": quote.get("open_interest"),
        "volume": quote.get("volume"),
        "expiry_date": data.get("expiry_date"),
        "underlying_ltp": data.get("underlying_ltp"),
        "retrieved_at": data.get("retrieved_at"),
    }

