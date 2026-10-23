"""Official public macro series provider for V6.

Provides reference data for:
1. FII / DII Daily Net Institutional Flows (NSE Official Reports, Daily 17:30 IST)
2. RBI / FBIL Reference Exchange Rates (USD/INR, Daily 13:30 IST)
3. US Treasury 10-Year Benchmark Yield (US Treasury / FRED, Daily Close)

Usage Limitations:
- These are daily settlement / reference indicators.
- They MUST NOT be represented as intraday streaming prices.
- If data is unavailable or retrieval fails, status remains MISSING_DATA.
- Nothing is invented: without var/market/macro_series.json there are no observations.
- A release older than its publication schedule allows is stale and has no direction.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from app.settings import REPO_ROOT

log = logging.getLogger("imm.macro_series")
MACRO_SERIES_PATH = REPO_ROOT / "var" / "market" / "macro_series.json"

# Published reference specifications
MACRO_SERIES_SPECS: dict[str, dict[str, Any]] = {
    "FII_DII_FLOWS": {
        "instrument": "FII_DII_FLOWS",
        "name": "FII / DII Net Institutional Flows",
        "source": "NSE Official Reports",
        "update_frequency": "DAILY_POST_CLOSE",
        "publication_delay": "Published daily at 17:30 IST",
        "units": "INR Crores",
        "intraday_eligible": False,
        "historical_coverage": "2024 to present",
        "limitations": "End-of-day cash segment net purchases/sales across institutional participants.",
    },
    "USDINR_REF": {
        "instrument": "USDINR_REF",
        "name": "FBIL / RBI USD/INR Reference Rate",
        "source": "Financial Benchmarks India / Reserve Bank of India",
        "update_frequency": "DAILY_REFERENCE",
        "publication_delay": "Published daily at 13:30 IST",
        "units": "INR per USD",
        "intraday_eligible": False,
        "historical_coverage": "Daily reference fixings",
        "limitations": "Official daily benchmark reference rate, not continuous OTC spot feed.",
    },
    "US10Y_YIELD": {
        "instrument": "US10Y_YIELD",
        "name": "US 10-Year Treasury Constant Maturity Yield",
        "source": "US Department of the Treasury / Federal Reserve",
        "update_frequency": "DAILY_CLOSE",
        "publication_delay": "Published at US session close",
        "units": "Percent per annum (% p.a.)",
        "intraday_eligible": False,
        "historical_coverage": "Daily benchmark yield curve",
        "limitations": "Sovereign debt benchmark yield; macro discount rate input.",
    },
}


def load_macro_series(path: Path | None = None) -> dict[str, Any]:
    """Load cached macro series from disk."""
    target = path or MACRO_SERIES_PATH
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("Failed loading macro series from %s: %s", target, exc)
        return {}


def save_macro_series(data: dict[str, Any], path: Path | None = None) -> None:
    """Save macro series to disk atomically."""
    target = path or MACRO_SERIES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(target)


IST = timezone(timedelta(hours=5, minutes=30))

# Business days a daily series may lag its latest expected publication before it is
# stale (1 tolerates a single exchange holiday).
STALE_AFTER_BUSINESS_DAYS = 1

# Minimum absolute FII net flow (INR crore) treated as a directional signal.
FII_SIGNAL_CRORES = 500.0


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _previous_business_day(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def latest_expected_date(now: datetime, publish_time: time, tz: timezone = IST) -> date:
    """The most recent business day whose release should already be published."""
    local = now.astimezone(tz)
    day = local.date()
    if day.weekday() < 5 and local.time() >= publish_time:
        return day
    return _previous_business_day(day) if day.weekday() < 5 else _previous_business_day(day + timedelta(days=1))


def business_days_behind(as_of: date, expected: date) -> int:
    behind, cursor = 0, expected
    while cursor > as_of:
        cursor = _previous_business_day(cursor)
        behind += 1
    return behind


def fii_dii_direction(fii: float, net: float) -> str:
    """Implication for Indian equities, driven by foreign flows.

    FII selling that domestic buying more than offsets (or the reverse) is MIXED, not
    bullish; flows below the signal size carry no direction.
    """
    if abs(fii) < FII_SIGNAL_CRORES:
        return "UNKNOWN"
    if (fii > 0) == (net > 0):
        return "BULLISH" if fii > 0 else "BEARISH"
    return "MIXED"


def _freshness(as_of_text: Any, now: datetime, publish_time: time, tz: timezone = IST) -> tuple[str | None, int | None, bool]:
    """(as_of ISO date, business days behind, stale). Unparseable dates are stale."""
    try:
        as_of = date.fromisoformat(str(as_of_text)[:10])
    except ValueError:
        return None, None, True
    behind = business_days_behind(as_of, latest_expected_date(now, publish_time, tz))
    return as_of.isoformat(), behind, behind > STALE_AFTER_BUSINESS_DAYS


def get_macro_observations(path: Path | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Convert cached macro reference series into structured Analysis observations.

    Only values present in the cached file are reported; nothing is invented or
    defaulted. A series older than its publication schedule allows is marked stale
    and carries no directional implication.
    """
    cached = load_macro_series(path)
    if not cached:
        return []
    now = now or datetime.now(timezone.utc)
    series_map = cached.get("series") or {}
    observations = []

    def _stale_note(as_of: str | None, behind: int | None) -> str:
        if as_of is None:
            return "STALE: the release date is missing or unreadable."
        return f"STALE: release dated {as_of} is {behind} business day(s) behind the latest expected release."

    # 1. FII / DII Flows (published 17:30 IST for that session)
    fii_data = series_map.get("FII_DII_FLOWS")
    if isinstance(fii_data, dict):
        spec = MACRO_SERIES_SPECS["FII_DII_FLOWS"]
        fii_val = _num(fii_data.get("fii_net_crores"))
        dii_val = _num(fii_data.get("dii_net_crores"))
        net_val = _num(fii_data.get("net_total_crores"))
        if net_val is None and fii_val is not None and dii_val is not None:
            net_val = fii_val + dii_val
        as_of, behind, stale = _freshness(fii_data.get("as_of_date"), now, time(17, 30))
        if fii_val is not None and dii_val is not None and net_val is not None and as_of is not None:
            direction = "UNKNOWN" if stale else fii_dii_direction(fii_val, net_val)
            limitations = [spec["limitations"], spec["publication_delay"]]
            if stale:
                limitations.insert(0, _stale_note(as_of, behind))
            obs_time = f"{as_of}T17:30:00+05:30"
            observations.append({
                "instrument": "FII_DII_FLOWS",
                "category": "MACRO",
                "claim": (f"NSE reported FII/DII net flows for {as_of}: FII {fii_val:+.1f} Cr, "
                          f"DII {dii_val:+.1f} Cr, Net total {net_val:+.1f} Cr."
                          + (" (stale)" if stale else "")),
                "claim_type": "OBSERVATION",
                "source_name": fii_data.get("source") or spec["source"],
                "provenance": "PROVIDER",
                "last_price": net_val,
                "unit": spec["units"],
                "directional_implication": direction,
                "time_horizon": "SHORT_TERM",
                "data_class": "VERIFIED_PROVIDER_DATA",
                "verification_status": fii_data.get("verification_status") or "UNVERIFIED",
                "retrieved_at": cached.get("retrieved_at"),
                "observed_at": obs_time,
                "published_at": obs_time,
                "stale": stale,
                "business_days_behind": behind,
                "details": {"fii_net_crores": fii_val, "dii_net_crores": dii_val, "net_total_crores": net_val},
                "limitations": limitations,
            })

    # 2. USD/INR Reference Rate (published 13:30 IST)
    fx_data = series_map.get("USDINR_REF")
    if isinstance(fx_data, dict):
        spec = MACRO_SERIES_SPECS["USDINR_REF"]
        rate = _num(fx_data.get("rate"))
        # FBIL publishes at 13:30 IST; the ECB fallback around 16:00 CET (20:30 IST, the later bound)
        from_ecb = str(fx_data.get("source") or "").startswith("ECB")
        release = time(20, 30) if from_ecb else time(13, 30)
        label = "ECB USD/INR cross rate" if from_ecb else "FBIL/RBI USD/INR reference rate"
        as_of, behind, stale = _freshness(fx_data.get("as_of_date"), now, release)
        if rate is not None and as_of is not None:
            obs_time = f"{as_of}T{release.strftime('%H:%M')}:00+05:30"
            observations.append({
                "instrument": "USDINR_REF",
                "category": "MACRO",
                "claim": f"{label} for {as_of}: {rate:.2f}." + (" (stale)" if stale else ""),
                "claim_type": "OBSERVATION",
                "source_name": fx_data.get("source") or spec["source"],
                "provenance": "PROVIDER",
                "last_price": rate,
                "unit": spec["units"],
                "directional_implication": "UNKNOWN",
                "time_horizon": "SHORT_TERM",
                "data_class": "VERIFIED_PROVIDER_DATA",
                "verification_status": fx_data.get("verification_status") or "UNVERIFIED",
                "retrieved_at": cached.get("retrieved_at"),
                "observed_at": obs_time,
                "published_at": obs_time,
                "stale": stale,
                "business_days_behind": behind,
                "limitations": ([_stale_note(as_of, behind)] if stale else []) + [spec["limitations"], spec["publication_delay"]],
            })

    # 3. US 10Y Yield (US close; dated in US Eastern business days, approximated here by UTC)
    y_data = series_map.get("US10Y_YIELD")
    if isinstance(y_data, dict):
        spec = MACRO_SERIES_SPECS["US10Y_YIELD"]
        y_val = _num(y_data.get("yield_pct"))
        as_of, behind, stale = _freshness(y_data.get("as_of_date"), now, time(21, 0), timezone.utc)
        if y_val is not None and as_of is not None:
            obs_time = f"{as_of}T21:00:00+00:00"
            observations.append({
                "instrument": "US10Y_YIELD",
                "category": "MACRO",
                "claim": f"US 10-Year Treasury yield closed at {y_val:.2f}% p.a. on {as_of}." + (" (stale)" if stale else ""),
                "claim_type": "OBSERVATION",
                "source_name": y_data.get("source") or spec["source"],
                "provenance": "PROVIDER",
                "last_price": y_val,
                "unit": spec["units"],
                "directional_implication": "UNKNOWN",
                "time_horizon": "SHORT_TERM",
                "data_class": "VERIFIED_PROVIDER_DATA",
                "verification_status": y_data.get("verification_status") or "UNVERIFIED",
                "retrieved_at": cached.get("retrieved_at"),
                "observed_at": obs_time,
                "published_at": obs_time,
                "stale": stale,
                "business_days_behind": behind,
                "limitations": ([_stale_note(as_of, behind)] if stale else []) + [spec["limitations"], spec["publication_delay"]],
            })

    return observations
