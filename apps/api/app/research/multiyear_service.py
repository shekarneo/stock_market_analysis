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


FORECAST_PATH = REPO_ROOT / "var" / "datasets" / "realistic_forecast.json"


def run_realistic_forecast(*, output: Path | None = None, log: Callable[[str], None] = print) -> tuple[dict, Path]:
    """Tune on the saved history and publish the next-session forecast (completed sessions only)."""
    from app.research import daily_research as dr
    from app.research.realistic_forecast import build_forecast

    def series(symbol: str, interval: str) -> list | None:
        doc = hl.load_series(symbol, interval)
        rows = completed_sessions(doc["candles"]) if doc and doc.get("candles") else None
        return rows or None

    daily = series("NSE-NIFTY", "1day")
    if daily is None:
        raise FileNotFoundError("No NIFTY daily history saved. Fetch NIFTY and INDIAVIX 1day history first.")
    intraday = series("NSE-NIFTY", "15minute")

    def as_bars(rows):
        return dr.daily_bars(rows) if rows else None

    report = build_forecast(
        nifty_daily=dr.daily_bars(daily),
        nifty_half_day=dr.half_day_bars(intraday) if intraday else None,
        vix=as_bars(series("NSE-INDIAVIX", "1day")),
        banknifty=as_bars(series("NSE-BANKNIFTY", "1day")),
        sensex=as_bars(series("BSE-SENSEX", "1day")),
        log=log,
    )
    report["generated_at"] = datetime.now().astimezone().isoformat()
    out = output or FORECAST_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    return report, out


def load_forecast(path: Path | None = None) -> dict | None:
    p = path or FORECAST_PATH
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def run_agent_evaluation(*, log: Callable[[str], None] = print) -> dict:
    """Replay the price-based agents on saved 15m history and score pending forward calls."""
    from app.analysis.agent_scorecard import score_from_saved_history, summarize
    from app.analysis.track_record import BACKTEST_PATH
    from app.research.agent_backtest import run_agent_backtest

    doc = hl.load_series("NSE-NIFTY", "15minute")
    if not doc or not doc.get("candles"):
        raise FileNotFoundError("No NIFTY 15minute history saved. Fetch NIFTY with the 15minute interval first.")
    report = run_agent_backtest(completed_sessions(doc["candles"]), log=log)
    BACKTEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = BACKTEST_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(BACKTEST_PATH)
    scored = score_from_saved_history()
    log(f"Agent backtest over {report['sessions']} sessions; scorecard: {scored}")
    return {"backtest": report, "scorecard_scoring": scored, "scorecard": summarize()}


INTRADAY_MODEL_DIR = REPO_ROOT / "var" / "datasets" / "intraday_range"
# Each index has its own model; India VIX (NSE) is the volatility input for all three
INTRADAY_INSTRUMENTS = {"NIFTY": "NSE-NIFTY", "BANKNIFTY": "NSE-BANKNIFTY", "SENSEX": "BSE-SENSEX"}
QUOTE_MAX_AGE_SECONDS = 180      # the poller refreshes every 15 s; older means the feed stopped
CLOSE_MATCH_TOLERANCE = 0.0005   # saved last close vs Groww's previous close (0.05%)


def intraday_model_path(instrument: str) -> Path:
    return INTRADAY_MODEL_DIR / f"{instrument}.json"


def run_intraday_range(instrument: str = "NIFTY", *, output: Path | None = None,
                       log: Callable[[str], None] = print) -> tuple[dict, Path]:
    """Evaluate and save one index's rest-of-day range model from saved 15m + daily history."""
    from app.research import daily_research as dr
    from app.research import intraday_range as ir

    def series(symbol: str, interval: str) -> list | None:
        doc = hl.load_series(symbol, interval)
        return (completed_sessions(doc["candles"]) or None) if doc and doc.get("candles") else None

    symbol = INTRADAY_INSTRUMENTS[instrument]
    r15, daily = series(symbol, "15minute"), series(symbol, "1day")
    if r15 is None or daily is None:
        raise FileNotFoundError(f"The intraday range model needs {instrument} 15minute and 1day history. Fetch them first.")
    vix = series("NSE-INDIAVIX", "1day")
    log(f"evaluating the {instrument} rest-of-day range model")
    model = ir.evaluate(ir.build_rows(r15, dr.daily_bars(daily), dr.daily_bars(vix) if vix else None))
    model["instrument"] = instrument
    model["generated_at"] = datetime.now().astimezone().isoformat()
    out = output or intraday_model_path(instrument)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(model, indent=2, default=str), encoding="utf-8")
    tmp.replace(out)
    return model, out


def run_intraday_ranges(*, log: Callable[[str], None] = print) -> dict[str, dict]:
    """Every index with saved history; one missing index does not stop the others."""
    results = {}
    for instrument in INTRADAY_INSTRUMENTS:
        try:
            model, path = run_intraday_range(instrument, log=log)
            results[instrument] = {"status": model.get("status"), "sessions": model.get("sessions"), "path": path.name}
        except FileNotFoundError as exc:
            results[instrument] = {"status": "NO_HISTORY", "message": str(exc)}
        log(f"{instrument} intraday range model: {results[instrument]['status']}")
    return results


def load_intraday_model(instrument: str = "NIFTY", path: Path | None = None) -> dict | None:
    p = path or intraday_model_path(instrument)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _model_summary(model: dict) -> dict:
    keys = ("instrument", "sessions", "first", "last", "holdout_from", "selected_on_development", "models",
            "holdout_mse_improvement_pct", "dm_holdout", "holdout_coverage_mean", "generated_at")
    return {k: model.get(k) for k in keys}


def live_intraday_forecast(instrument: str = "NIFTY", *, now: datetime | None = None,
                           observations: list[dict] | None = None, model: dict | None = None) -> dict:
    """Rest-of-day range for one index from the latest stored Groww quote. Never fills a missing input."""
    from app.research import daily_research as dr
    from app.research import intraday_range as ir

    symbol = INTRADAY_INSTRUMENTS[instrument]
    model = model if model is not None else load_intraday_model(instrument)
    if model is None or model.get("status") != "EVALUATED":
        status = model.get("status") if model else None
        return {"instrument": instrument, "status": "MODEL_MISSING",
                "message": (f"The {instrument} model did not pass evaluation ({status})." if status else
                            f"Run the research (Fetch {instrument} 15minute + 1day history, then Run) to train the model.")}
    out: dict[str, Any] = {"instrument": instrument, "model": _model_summary(model)}
    now = (now or datetime.now(hl.IST)).astimezone(hl.IST)
    out["now"] = now.isoformat()
    if now.weekday() >= 5 or now.time() >= time(15, 30):
        return {**out, "status": "MARKET_CLOSED", "message": "The cash session is closed; the next forecast starts at 09:30 IST."}
    if now.time() < time(9, 30):
        return {**out, "status": "PRE_OPEN", "message": "The first rest-of-day forecast is at 09:30 IST, after one 15-minute bar."}
    k = min(max((now.hour * 60 + now.minute - (9 * 60 + 15)) // 15, 1), ir.SESSION_BARS - 1)

    if observations is None:
        from app.market.live_quotes import stored_observations

        observations = stored_observations()
    quote = next((o for o in observations if o.get("instrument") == instrument and o.get("last_price") is not None), None)
    if quote is None or not isinstance(quote.get("ohlc"), dict):
        return {**out, "status": "NO_LIVE_QUOTE",
                "message": f"No {instrument} quote with the day's open/high/low is stored. Check the Groww feed."}
    try:
        age = (now - datetime.fromisoformat(quote["retrieved_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    if age is None or age > QUOTE_MAX_AGE_SECONDS:
        return {**out, "status": "STALE_QUOTE", "quote_retrieved_at": quote.get("retrieved_at"),
                "message": f"The stored {instrument} quote is older than {QUOTE_MAX_AGE_SECONDS} s; the live feed is not updating."}
    ohlc, price = quote["ohlc"], float(quote["last_price"])
    out["quote"] = {"last_price": price, "ohlc": ohlc, "retrieved_at": quote["retrieved_at"]}

    today = now.date().isoformat()
    doc, vdoc = hl.load_series(symbol, "1day"), hl.load_series("NSE-INDIAVIX", "1day")
    daily = [b for b in dr.daily_bars(doc["candles"]) if b.day < today] if doc and doc.get("candles") else []
    vix = [b for b in dr.daily_bars(vdoc["candles"]) if b.day < today] if vdoc and vdoc.get("candles") else []
    if len(daily) < 22:
        return {**out, "status": "HISTORY_MISSING", "message": f"Fetch {instrument} and INDIAVIX daily history first."}
    last = daily[-1]
    if all(abs(float(ohlc[f]) - getattr(last, f)) < 0.01 for f in ("open", "high", "low")) and abs(price - last.close) < 0.01:
        return {**out, "status": "NO_SESSION_TODAY",
                "message": f"Groww's quote is the {last.day} session again: there is no session today (holiday)."}
    if abs(float(ohlc["close"]) / last.close - 1) > CLOSE_MATCH_TOLERANCE or not vix or vix[-1].day != last.day:
        return {**out, "status": "HISTORY_BEHIND",
                "message": (f"The saved daily history ends {last.day} (close {last.close}, VIX {vix[-1].day if vix else 'none'}), "
                            f"but Groww's previous close is {ohlc['close']}. Update the daily history first.")}
    ctx = ir.context_for(today, daily, vix)
    result = ir.forecast_from_quote(model, ctx=ctx, k=k, open_=float(ohlc["open"]), high=float(ohlc["high"]),
                                    low=float(ohlc["low"]), price=price)
    return {**out, **result}


def agent_evaluation_state() -> dict:
    from app.analysis.agent_scorecard import summarize
    from app.analysis.track_record import BACKTEST_PATH

    backtest = json.loads(BACKTEST_PATH.read_text(encoding="utf-8")) if BACKTEST_PATH.is_file() else None
    return {"backtest": backtest, "scorecard": summarize()}
