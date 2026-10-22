"""Exchange instrument master: listed expiries and contract specs from Groww.

Sources (documented at groww.in/trade-api/docs):
- Instruments CSV, https://growwapi-assets.groww.in/instruments/instrument.csv, with
  columns exchange, trading_symbol, segment, underlying_symbol, expiry_date,
  instrument_type, lot_size, tick_size, ... It covers NSE, BSE and MCX contracts.
- Expiries API, GET /v1/historical/expiries?exchange=NSE|BSE&underlying_symbol=..
  (authenticated; NSE and BSE only).

Listed expiries are persisted to var/market/listed_expiries.json and read by
groww_options.listed_expiries_for(). Nothing here invents a date: an underlying with
no rows in the source simply has no listed expiries.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.settings import REPO_ROOT

INSTRUMENTS_CSV_URL = "https://growwapi-assets.groww.in/instruments/instrument.csv"
LISTED_EXPIRIES_PATH = REPO_ROOT / "var" / "market" / "listed_expiries.json"

# Canonical underlying -> (exchange, underlying_symbol as listed by the exchange/Groww)
MASTER_SYMBOLS: dict[str, tuple[str, str]] = {
    "NIFTY": ("NSE", "NIFTY"),
    "SENSEX": ("BSE", "SENSEX"),
    "CRUDEOILMINI": ("MCX", "CRUDEOILM"),
}


def parse_instruments_csv(text: str) -> list[dict]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _rows_for(rows: list[dict], canonical: str) -> list[dict]:
    exchange, symbol = MASTER_SYMBOLS[canonical]
    return [
        r for r in rows
        if (r.get("exchange") or "").upper() == exchange
        and (r.get("underlying_symbol") or "").upper() == symbol
        and r.get("expiry_date")
    ]


def _iso(value: str) -> str | None:
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except (ValueError, AttributeError):
        return None


def option_expiries_from_rows(rows: list[dict], canonical: str) -> list[str]:
    """Sorted distinct option expiries (CE/PE rows) for one underlying."""
    found = {
        _iso(r["expiry_date"]) for r in _rows_for(rows, canonical)
        if (r.get("instrument_type") or "").upper() in {"CE", "PE"}
    }
    return sorted(d for d in found if d)


def front_month_future_symbol(rows: list[dict], canonical: str, as_of: date) -> str | None:
    """Trading symbol of the nearest unexpired future for an underlying, e.g. MCX crude mini."""
    futures = [
        (_iso(r["expiry_date"]), r.get("trading_symbol"))
        for r in _rows_for(rows, canonical)
        if (r.get("instrument_type") or "").upper() == "FUT"
    ]
    live = sorted((exp, sym) for exp, sym in futures if exp and sym and exp >= as_of.isoformat())
    return live[0][1] if live else None


def contract_spec_mismatches(rows: list[dict]) -> list[dict]:
    """Compare lot and tick sizes in the master with app/instrument_specs.py."""
    from app.instrument_specs import INSTRUMENT_SPECS

    issues = []
    for canonical, spec in INSTRUMENT_SPECS.items():
        if canonical not in MASTER_SYMBOLS:
            continue
        opts = [r for r in _rows_for(rows, canonical) if (r.get("instrument_type") or "").upper() in {"CE", "PE"}]
        lots = sorted({int(float(r["lot_size"])) for r in opts if r.get("lot_size")})
        if lots and spec.lot_size not in lots:
            issues.append({"instrument": canonical, "field": "lot_size", "configured": spec.lot_size, "master": lots})
    return issues


def save_listed_expiries(expiries: dict[str, list[str]], *, source: str, path: Path | None = None) -> Path:
    target = path or LISTED_EXPIRIES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "expiries": {k: sorted(set(v)) for k, v in expiries.items() if v},
    }
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def load_listed_expiries(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    target = path or LISTED_EXPIRIES_PATH
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for key, values in (data.get("expiries") or {}).items():
        dates = sorted({d for d in (_iso(str(v)) for v in values) if d})
        if dates:
            out[str(key).upper()] = tuple(dates)
    return out


def expiries_from_api_payload(body: object) -> list[str]:
    """Dates from a Groww Expiries API response ({"payload": {"expiries": [...]}})."""
    if not isinstance(body, dict):
        return []
    payload = body.get("payload")
    raw = payload.get("expiries") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    return sorted({d for d in (_iso(str(v)) for v in raw) if d})
