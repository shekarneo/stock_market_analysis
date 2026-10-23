"""Multi-year historical candles from the Groww Historical Data API.

Endpoint: GET https://api.groww.in/v1/historical/candles
    exchange (NSE|BSE), segment (CASH|FNO), groww_symbol, start_time, end_time,
    candle_interval. Data is available from 2020. Each request is limited to:
    1-5 min: 30 days; 10-30 min: 90 days; 1 hour .. 1 month: 180 days.
    Candle rows: [timestamp, open, high, low, close, volume, open_interest].

MCX and currency segments are not served by this endpoint, so crude oil and USD/INR
history cannot be loaded here; nothing is substituted for them.

Each series is saved to var/datasets/history/<groww_symbol>_<interval>.json with the
requests made, so a dataset can be traced back to its calls.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.settings import REPO_ROOT

HISTORY_DIR = REPO_ROOT / "var" / "datasets" / "history"
IST = timezone(timedelta(hours=5, minutes=30))

MAX_DAYS_PER_REQUEST = {
    "1minute": 30, "2minute": 30, "3minute": 30, "5minute": 30,
    "10minute": 90, "15minute": 90, "30minute": 90,
    "1hour": 180, "4hour": 180, "1day": 180, "1week": 180, "1month": 180,
}

# Research series: (exchange, segment, groww_symbol). Index symbols follow Groww's
# EXCHANGE-SYMBOL convention; verify any that return no candles against the instrument CSV.
DEFAULT_SERIES: dict[str, tuple[str, str, str]] = {
    "NIFTY": ("NSE", "CASH", "NSE-NIFTY"),
    "BANKNIFTY": ("NSE", "CASH", "NSE-BANKNIFTY"),
    "INDIAVIX": ("NSE", "CASH", "NSE-INDIAVIX"),
    "SENSEX": ("BSE", "CASH", "BSE-SENSEX"),
}


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def request_windows(start: datetime, end: datetime, interval: str) -> list[Window]:
    """Split [start, end) into windows no longer than the API allows for the interval."""
    if interval not in MAX_DAYS_PER_REQUEST:
        raise ValueError(f"Unsupported candle interval {interval!r}.")
    if end <= start:
        return []
    span = timedelta(days=MAX_DAYS_PER_REQUEST[interval])
    windows, cursor = [], start
    while cursor < end:
        stop = min(cursor + span, end)
        windows.append(Window(cursor, stop))
        cursor = stop
    return windows


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(IST)
    if isinstance(value, str):
        text = value.strip().replace(" ", "T", 1)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)
    return None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN -> None


def normalize_candles(raw: list) -> tuple[list[list], int]:
    """Validated rows [iso_ts, o, h, l, c, volume|None, oi|None]; returns (rows, rejected)."""
    rows, rejected = [], 0
    for item in raw or []:
        if not isinstance(item, (list, tuple)) or len(item) < 5:
            rejected += 1
            continue
        ts = _parse_ts(item[0])
        o, h, l, c = (_num(v) for v in item[1:5])
        if ts is None or None in (o, h, l, c) or min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
            rejected += 1
            continue
        vol = _num(item[5]) if len(item) > 5 else None
        oi = _num(item[6]) if len(item) > 6 else None
        rows.append([ts.isoformat(), o, h, l, c, vol, oi])
    return rows, rejected


def merge_rows(existing: list[list], new: list[list]) -> list[list]:
    """Union by timestamp; a later fetch replaces an earlier row for the same bar."""
    merged = {row[0]: row for row in existing}
    for row in new:
        merged[row[0]] = row
    return [merged[k] for k in sorted(merged)]


def series_path(groww_symbol: str, interval: str, root: Path | None = None) -> Path:
    return (root or HISTORY_DIR) / f"{groww_symbol}_{interval}.json"


def load_series(groww_symbol: str, interval: str, root: Path | None = None) -> dict | None:
    path = series_path(groww_symbol, interval, root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_series(
    fetch_window: Callable[[Window], Any],
    *,
    exchange: str,
    segment: str,
    groww_symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    root: Path | None = None,
    pause_seconds: float = 0.35,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Fetch [start, end) window by window, merge with any saved series, and persist.

    fetch_window(window) must return the decoded JSON body (dict) or raise. Failed
    windows are recorded and skipped; nothing is filled in for them.
    """
    saved = load_series(groww_symbol, interval, root) or {}
    rows: list[list] = list(saved.get("candles") or [])
    requests_log: list[dict] = list(saved.get("requests") or [])
    rejected_total = 0
    for index, window in enumerate(request_windows(start, end, interval)):
        if index:
            sleeper(pause_seconds)
        entry = {"start": window.start.isoformat(), "end": window.end.isoformat(),
                 "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            body = fetch_window(window)
            payload = body.get("payload", body) if isinstance(body, dict) else {}
            raw = payload.get("candles") if isinstance(payload, dict) else None
            new_rows, rejected = normalize_candles(raw or [])
            rows = merge_rows(rows, new_rows)
            rejected_total += rejected
            entry.update(status="OK", candles=len(new_rows), rejected=rejected)
        except Exception as exc:  # recorded, never filled
            entry.update(status="FAILED", error=f"{exc.__class__.__name__}: {exc}"[:300])
        requests_log.append(entry)

    document = {
        "schema": "groww-history-1",
        "exchange": exchange,
        "segment": segment,
        "groww_symbol": groww_symbol,
        "interval": interval,
        "source": "GET /v1/historical/candles",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "first": rows[0][0] if rows else None,
        "last": rows[-1][0] if rows else None,
        "candle_count": len(rows),
        "rejected_rows": rejected_total,
        "failed_windows": sum(1 for r in requests_log if r.get("status") == "FAILED"),
        "requests": requests_log[-2000:],
        "candles": rows,
    }
    path = series_path(groww_symbol, interval, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(document), encoding="utf-8")
    tmp.replace(path)
    return document


def groww_window_fetcher(caller, access_token: str, *, exchange: str, segment: str, groww_symbol: str, interval: str):
    """Adapter: one Groww historical-candles request per window."""
    from app.integrations.groww import read_historical_candles

    def fetch(window: Window) -> Any:
        params = {
            "exchange": exchange,
            "segment": segment,
            "groww_symbol": groww_symbol,
            "start_time": window.start.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": window.end.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S"),
            "candle_interval": interval,
        }
        result = read_historical_candles(caller, access_token, params)
        if result.status_code != 200:
            raise RuntimeError(f"HTTP {result.status_code}: {result.text[:200]}")
        return result.body

    return fetch
