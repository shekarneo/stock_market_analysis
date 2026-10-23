"""Daily options positioning (put/call open interest) for NIFTY from Groww history.

For each listed weekly expiry, near-the-money CE and PE contracts are looked up with the
Contracts API and their daily candles (which carry open interest) are fetched with the
Historical Candles API (segment FNO). The daily feature is the PE/CE open-interest ratio
of the nearest unexpired expiry, within a strike band around the previous close.

This takes several thousand requests for 2020 onwards; it is optional and resumable
(results are cached per contract under var/datasets/history/options/).
Groww symbols look like NSE-NIFTY-04Jan24-19200-CE.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Callable

from app.market.history_loader import HISTORY_DIR, IST, Window, normalize_candles

OPTIONS_DIR = HISTORY_DIR / "options"
_SYMBOL = re.compile(r"-(\d+(?:\.\d+)?)-(CE|PE)$")


def parse_contract(symbol: str) -> tuple[float, str] | None:
    m = _SYMBOL.search(symbol or "")
    return (float(m.group(1)), m.group(2)) if m else None


def band_contracts(symbols: list[str], reference_price: float, *, strike_step: int, band_strikes: int) -> list[str]:
    """Contracts whose strike is within band_strikes steps of the reference price."""
    out = []
    for sym in symbols:
        parsed = parse_contract(sym)
        if parsed and abs(parsed[0] - reference_price) <= band_strikes * strike_step:
            out.append(sym)
    return sorted(out)


def fetch_contract_daily(
    fetch_candles: Callable[[str, Window], dict],
    symbol: str,
    expiry: date,
    *,
    lookback_days: int = 30,
    root: Path | None = None,
) -> list[list]:
    """Daily candles (with OI) for one contract over its last lookback_days; cached."""
    folder = root or OPTIONS_DIR
    cache = folder / f"{symbol}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    end = datetime.combine(expiry + timedelta(days=1), dtime(0, 0), IST)
    start = end - timedelta(days=lookback_days)
    body = fetch_candles(symbol, Window(start, end))
    payload = body.get("payload", body) if isinstance(body, dict) else {}
    rows, _ = normalize_candles((payload or {}).get("candles") or [])
    folder.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def daily_pcr(
    expiry_contracts: dict[date, dict[str, list[list]]],
) -> dict[str, dict]:
    """Per trading day: PE/CE open-interest ratio of the nearest unexpired expiry.

    expiry_contracts maps expiry -> {contract symbol -> daily rows}. A day appears only
    when both CE and PE open interest are reported; nothing is filled.
    """
    by_day: dict[str, dict[date, dict[str, float]]] = {}
    for expiry, contracts in expiry_contracts.items():
        for symbol, rows in contracts.items():
            parsed = parse_contract(symbol)
            if not parsed:
                continue
            side = parsed[1]
            for row in rows:
                day = row[0][:10]
                oi = row[6]
                if oi is None or date.fromisoformat(day) > expiry:
                    continue
                slot = by_day.setdefault(day, {}).setdefault(expiry, {"CE": 0.0, "PE": 0.0, "n_ce": 0, "n_pe": 0})
                slot[side] += oi
                slot["n_ce" if side == "CE" else "n_pe"] += 1
    out = {}
    for day, expiries in by_day.items():
        d = date.fromisoformat(day)
        live = sorted(e for e in expiries if e >= d)
        if not live:
            continue
        nearest = expiries[live[0]]
        if nearest["n_ce"] and nearest["n_pe"] and nearest["CE"] > 0:
            out[day] = {"pcr_oi": nearest["PE"] / nearest["CE"], "expiry": live[0].isoformat(),
                        "ce_oi": nearest["CE"], "pe_oi": nearest["PE"]}
    return dict(sorted(out.items()))


def build_pcr_history(
    *,
    list_expiries: Callable[[int], list[str]],
    list_contracts: Callable[[str], list[str]],
    fetch_candles: Callable[[str, Window], dict],
    reference_closes: dict[str, float],
    start: date,
    end: date,
    strike_step: int,
    band_strikes: int = 5,
    lookback_days: int = 12,
    root: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Fetch near-the-money CE/PE daily OI for every expiry in [start, end] and compute PCR.

    The strike band for an expiry is centred on the last close at least lookback_days
    before expiry, so contract selection never uses prices after the first PCR day.
    Expiries without a reference close, or whose contract list fails, are skipped and
    counted. Saves var/datasets/history/options/pcr_daily.json.
    """
    folder = root or OPTIONS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    closes = sorted(reference_closes.items())
    expiries: set[str] = set()
    for year in range(start.year, end.year + 1):
        expiries.update(e for e in list_expiries(year) if start.isoformat() <= e <= end.isoformat())
    data: dict[date, dict[str, list[list]]] = {}
    skipped: list[dict] = []
    for exp in sorted(expiries):
        expiry = date.fromisoformat(exp)
        cutoff = (expiry - timedelta(days=lookback_days)).isoformat()
        before = [c for d, c in closes if d <= cutoff]
        if not before:
            skipped.append({"expiry": exp, "reason": "NO_REFERENCE_CLOSE"})
            continue
        cache = folder / f"contracts_{exp}.json"
        try:
            symbols = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else list_contracts(exp)
        except Exception as exc:  # recorded, never filled
            skipped.append({"expiry": exp, "reason": f"CONTRACTS_FAILED: {exc}"[:200]})
            continue
        if not cache.is_file():
            cache.write_text(json.dumps(symbols), encoding="utf-8")
        chosen = band_contracts(symbols, before[-1], strike_step=strike_step, band_strikes=band_strikes)
        contracts: dict[str, list[list]] = {}
        for sym in chosen:
            try:
                contracts[sym] = fetch_contract_daily(fetch_candles, sym, expiry, lookback_days=lookback_days, root=folder)
            except Exception as exc:
                skipped.append({"expiry": exp, "contract": sym, "reason": f"CANDLES_FAILED: {exc}"[:200]})
        data[expiry] = contracts
        log(f"{exp}: {len(chosen)} contracts")
    pcr = daily_pcr(data)
    document = {"schema": "groww-pcr-1", "strike_band": band_strikes, "strike_step": strike_step,
                "expiries": len(data), "skipped": skipped, "days": len(pcr), "pcr": pcr}
    (folder / "pcr_daily.json").write_text(json.dumps(document), encoding="utf-8")
    return document


def load_pcr(root: Path | None = None) -> dict[str, dict] | None:
    path = (root or OPTIONS_DIR) / "pcr_daily.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("pcr") or None
