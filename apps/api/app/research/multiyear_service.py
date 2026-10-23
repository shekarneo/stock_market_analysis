"""Shared entry points for the multi-year research (used by the CLI and the API).

fetch_history downloads Groww candles (and optionally the NIFTY daily PCR) into
var/datasets/history/; run_daily_research builds the daily / half-day report.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable

from app.market import history_loader as hl
from app.settings import REPO_ROOT

REPORT_PATH = REPO_ROOT / "var" / "datasets" / "research_daily_report.json"
INTERVALS = ("1day", "15minute")


def history_inventory(root: Path | None = None) -> dict:
    """Saved series and PCR without their candles."""
    from app.market.options_history import OPTIONS_DIR

    series = []
    for name, (exchange, segment, symbol) in hl.DEFAULT_SERIES.items():
        for interval in INTERVALS:
            doc = hl.load_series(symbol, interval, root)
            series.append({
                "name": name, "exchange": exchange, "groww_symbol": symbol, "interval": interval,
                "saved": doc is not None,
                "candle_count": doc.get("candle_count") if doc else None,
                "first": doc.get("first") if doc else None,
                "last": doc.get("last") if doc else None,
                "failed_windows": doc.get("failed_windows") if doc else None,
                "rejected_rows": doc.get("rejected_rows") if doc else None,
                "updated_at": doc.get("updated_at") if doc else None,
            })
    pcr = None
    pcr_path = (root / "options" if root else OPTIONS_DIR) / "pcr_daily.json"
    if pcr_path.is_file():
        doc = json.loads(pcr_path.read_text(encoding="utf-8"))
        days = sorted((doc.get("pcr") or {}).keys())
        pcr = {"days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
               "expiries": doc.get("expiries"), "skipped": len(doc.get("skipped") or [])}
    return {"series": series, "pcr": pcr}


def fetch_history(
    *,
    token: str,
    caller: Any,
    symbols: list[str],
    start: datetime,
    end: datetime,
    intervals: list[str],
    options: bool = False,
    band_strikes: int = 5,
    log: Callable[[str], None] = print,
) -> dict:
    """Download each symbol/interval; failed windows are counted, never filled."""
    from app.integrations.groww import read_contracts, read_expiries, read_historical_candles
    from app.instrument_specs import strike_step_for
    from app.market.instrument_master import expiries_from_api_payload

    unknown = [s for s in symbols if s not in hl.DEFAULT_SERIES]
    if unknown:
        raise ValueError(f"Unknown symbols {unknown}; choose from {sorted(hl.DEFAULT_SERIES)}")
    bad = [i for i in intervals if i not in INTERVALS]
    if bad:
        raise ValueError(f"Unsupported intervals {bad}; choose from {list(INTERVALS)}")
    results, failures = [], 0
    for interval in intervals:
        for name in symbols:
            exchange, segment, groww_symbol = hl.DEFAULT_SERIES[name]
            fetch = hl.groww_window_fetcher(caller, token, exchange=exchange, segment=segment,
                                            groww_symbol=groww_symbol, interval=interval)
            doc = hl.fetch_series(fetch, exchange=exchange, segment=segment, groww_symbol=groww_symbol,
                                  interval=interval, start=start, end=end)
            failures += doc["failed_windows"]
            results.append({"name": name, "interval": interval, "candle_count": doc["candle_count"],
                            "first": doc["first"], "last": doc["last"],
                            "failed_windows": doc["failed_windows"], "rejected_rows": doc["rejected_rows"]})
            log(f"{name} {interval}: {doc['candle_count']} candles {doc['first']} .. {doc['last']}"
                f" (failed windows {doc['failed_windows']}, rejected rows {doc['rejected_rows']})")

    pcr_summary = None
    if options:
        from app.market.options_history import build_pcr_history

        nifty = hl.load_series("NSE-NIFTY", "1day")
        if not nifty or not nifty.get("candles"):
            raise ValueError("Options PCR needs NIFTY 1day history first.")
        closes = {row[0][:10]: row[4] for row in nifty["candles"]}

        def list_expiries(year: int) -> list[str]:
            result = read_expiries(caller, token, exchange="NSE", underlying_symbol="NIFTY", year=year)
            return expiries_from_api_payload(result.body) if result.status_code == 200 else []

        def list_contracts(expiry: str) -> list[str]:
            result = read_contracts(caller, token, exchange="NSE", underlying_symbol="NIFTY", expiry_date=expiry)
            if result.status_code != 200:
                raise RuntimeError(f"HTTP {result.status_code}")
            payload = result.body.get("payload") if isinstance(result.body, dict) else None
            return list((payload or {}).get("contracts") or [])

        def fetch_candles(symbol: str, window: hl.Window) -> dict:
            result = read_historical_candles(caller, token, {
                "exchange": "NSE", "segment": "FNO", "groww_symbol": symbol,
                "start_time": window.start.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": window.end.strftime("%Y-%m-%d %H:%M:%S"),
                "candle_interval": "1day",
            })
            if result.status_code != 200:
                raise RuntimeError(f"HTTP {result.status_code}")
            return result.body

        doc = build_pcr_history(list_expiries=list_expiries, list_contracts=list_contracts, fetch_candles=fetch_candles,
                                reference_closes=closes, start=start.date(), end=end.date(),
                                strike_step=strike_step_for("NIFTY"), band_strikes=band_strikes, log=log)
        pcr_summary = {"days": doc["days"], "expiries": doc["expiries"], "skipped": len(doc["skipped"])}
        log(f"PCR: {doc['days']} days from {doc['expiries']} expiries; skipped {len(doc['skipped'])}")
    return {"series": results, "failed_windows": failures, "pcr": pcr_summary}


SESSION_CLOSE_BUFFER = time(15, 45)


def completed_sessions(rows: list[list], now: datetime | None = None) -> list[list]:
    """Drop today's rows until the session has closed: a forming candle is not a result."""
    now = (now or datetime.now(hl.IST)).astimezone(hl.IST)
    if now.time() >= SESSION_CLOSE_BUFFER:
        return rows
    today = now.date().isoformat()
    return [r for r in rows if str(r[0])[:10] != today]


def run_daily_research(
    *,
    with_pcr: bool = False,
    initial_train: int = 500,
    step: int = 20,
    output: Path | None = None,
) -> tuple[dict, Path]:
    """Build the report from saved history. Raises FileNotFoundError without NIFTY data."""
    from app.market.options_history import load_pcr
    from app.research import daily_research as dr

    def series(symbol: str, interval: str) -> list | None:
        doc = hl.load_series(symbol, interval)
        rows = completed_sessions(doc["candles"]) if doc and doc.get("candles") else None
        return rows or None

    daily = series("NSE-NIFTY", "1day")
    intraday = series("NSE-NIFTY", "15minute")
    if daily is None and intraday is None:
        raise FileNotFoundError("No NIFTY history saved. Fetch NIFTY 1day (and INDIAVIX) first.")
    nifty_daily = dr.daily_bars(daily) if daily else dr.daily_from_intraday(intraday)

    def as_bars(rows):
        return dr.daily_bars(rows) if rows else None

    report = dr.run_research(
        nifty_daily=nifty_daily,
        nifty_half_day=dr.half_day_bars(intraday) if intraday else None,
        vix=as_bars(series("NSE-INDIAVIX", "1day")),
        banknifty=as_bars(series("NSE-BANKNIFTY", "1day")),
        sensex=as_bars(series("BSE-SENSEX", "1day")),
        pcr=load_pcr() if with_pcr else None,
        cfg=dr.WalkForwardConfig(initial_train=initial_train, step=step),
    )
    report["generated_at"] = datetime.now().astimezone().isoformat()
    out = output or REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    return report, out


def load_report(path: Path | None = None) -> dict | None:
    p = path or REPORT_PATH
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
