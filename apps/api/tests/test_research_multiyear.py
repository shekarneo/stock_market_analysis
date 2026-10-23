"""Multi-year research: Groww history loader, options PCR, daily/half-day evaluation."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.market import history_loader as hl
from app.market.options_history import band_contracts, daily_pcr, parse_contract
from app.research import daily_research as dr

IST = hl.IST


# ------------------------------------------------------------------- loader

def test_request_windows_respect_interval_limits():
    start = datetime(2020, 1, 1, tzinfo=IST)
    end = datetime(2021, 1, 1, tzinfo=IST)
    daily = hl.request_windows(start, end, "1day")
    assert all(w.end - w.start <= timedelta(days=180) for w in daily)
    assert daily[0].start == start and daily[-1].end == end
    assert all(a.end == b.start for a, b in zip(daily, daily[1:]))
    assert len(hl.request_windows(start, end, "15minute")) == math.ceil(366 / 90)
    assert len(hl.request_windows(start, end, "5minute")) == math.ceil(366 / 30)
    with pytest.raises(ValueError):
        hl.request_windows(start, end, "7minute")
    assert hl.request_windows(end, start, "1day") == []


def test_normalize_rejects_bad_geometry_and_keeps_missing_volume_as_none():
    rows, rejected = hl.normalize_candles([
        ["2024-01-02 09:15:00", 100, 101, 99, 100.5, 1000, None],
        ["2024-01-02T09:30:00", 100.5, 100, 99, 100.2],       # high below open
        [1704167700, 100.2, 100.4, 100.0, 100.3],              # epoch seconds
        ["bad", 1, 1, 1, 1],
        ["2024-01-02 09:45:00", 100, 101, 99, None],
    ])
    assert rejected == 3
    assert rows[0] == ["2024-01-02T09:15:00+05:30", 100.0, 101.0, 99.0, 100.5, 1000.0, None]
    assert rows[1][5] is None and rows[1][6] is None
    assert rows[1][0].endswith("+05:30")


def test_fetch_series_records_failed_windows_and_merges(tmp_path):
    calls = []

    def fetch(window):
        calls.append(window)
        if len(calls) == 2:
            raise RuntimeError("HTTP 429")
        day = window.start.strftime("%Y-%m-%d")
        return {"status": "SUCCESS", "payload": {"candles": [[f"{day} 15:30:00", 10, 11, 9, 10.5, 5, None]]}}

    kwargs = dict(exchange="NSE", segment="CASH", groww_symbol="NSE-NIFTY", interval="1day",
                  root=tmp_path, sleeper=lambda s: None)
    doc = hl.fetch_series(fetch, start=datetime(2020, 1, 1, tzinfo=IST), end=datetime(2021, 1, 1, tzinfo=IST), **kwargs)
    assert len(calls) == 3
    assert doc["failed_windows"] == 1 and doc["candle_count"] == 2
    assert hl.load_series("NSE-NIFTY", "1day", tmp_path)["candle_count"] == 2
    # A second run merges with the saved file; the earlier failure stays in the log.
    calls.clear()
    doc = hl.fetch_series(fetch, start=datetime(2021, 1, 1, tzinfo=IST), end=datetime(2021, 2, 1, tzinfo=IST), **kwargs)
    assert doc["candle_count"] == 3 and doc["failed_windows"] == 1


# ------------------------------------------------------------------- options

def test_parse_and_band_contracts():
    assert parse_contract("NSE-NIFTY-04Jan24-19200-CE") == (19200.0, "CE")
    assert parse_contract("NSE-NIFTY-04Jan24-FUT") is None
    syms = [f"NSE-NIFTY-04Jan24-{k}-{s}" for k in range(19000, 19500, 50) for s in ("CE", "PE")]
    band = band_contracts(syms, 19210, strike_step=50, band_strikes=2)
    assert {parse_contract(s)[0] for s in band} == {19150.0, 19200.0, 19250.0, 19300.0}  # |K-19210| <= 100
    assert len(band) == 8


def test_daily_pcr_uses_nearest_live_expiry_and_requires_both_sides():
    e1, e2 = date(2024, 1, 4), date(2024, 1, 11)
    data = {
        e1: {"NSE-NIFTY-04Jan24-19200-CE": [["2024-01-03T15:30:00+05:30", 1, 1, 1, 1, 0, 100.0]],
             "NSE-NIFTY-04Jan24-19200-PE": [["2024-01-03T15:30:00+05:30", 1, 1, 1, 1, 0, 150.0]]},
        e2: {"NSE-NIFTY-11Jan24-19200-CE": [["2024-01-03T15:30:00+05:30", 1, 1, 1, 1, 0, 400.0],
                                            ["2024-01-05T15:30:00+05:30", 1, 1, 1, 1, 0, 400.0]],
             "NSE-NIFTY-11Jan24-19200-PE": [["2024-01-03T15:30:00+05:30", 1, 1, 1, 1, 0, 100.0],
                                            ["2024-01-08T15:30:00+05:30", 1, 1, 1, 1, 0, None]]},
    }
    out = daily_pcr(data)
    assert out["2024-01-03"]["pcr_oi"] == pytest.approx(1.5) and out["2024-01-03"]["expiry"] == "2024-01-04"
    assert "2024-01-05" not in out  # PE missing for the nearest live expiry
    assert "2024-01-08" not in out  # OI None is not treated as zero


# -------------------------------------------------------------- synthetic data

def _garch_bars(n=1100, seed=3, drift=0.0):
    rng = np.random.default_rng(seed)
    bars, vix = [], []
    price, var = 10000.0, 1e-4
    day0 = date(2020, 1, 1)
    for t in range(n):
        var = 2e-6 + 0.85 * var + 0.12 * (math.sqrt(var) * rng.standard_normal()) ** 2
        sd = math.sqrt(var)
        r = drift + sd * rng.standard_normal()
        o = price * math.exp(0.1 * sd * rng.standard_normal())
        c = price * math.exp(r)
        rng_hl = sd * math.sqrt(4 * math.log(2)) * abs(1 + 0.3 * rng.standard_normal())
        h = max(o, c) * math.exp(rng_hl / 2)
        low = min(o, c) * math.exp(-rng_hl / 2)
        day = (day0 + timedelta(days=t)).isoformat()
        bars.append(dr.Bar(day, day, o, h, low, c))
        v = 100 * math.sqrt(var * dr.TRADING_DAYS) * math.exp(0.05 * rng.standard_normal())
        vix.append(dr.Bar(day, day, v, v, v, v))
        price = c
    return bars, vix


def test_half_day_bars_split_and_drop_incomplete_halves():
    rows = []
    for d in ("2024-01-02", "2024-01-03"):
        t = datetime.fromisoformat(f"{d}T09:15:00+05:30")
        for i in range(25):
            if d == "2024-01-03" and i >= 15:  # session cut short: PM incomplete
                break
            ts = (t + timedelta(minutes=15 * i)).isoformat()
            rows.append([ts, 100 + i, 101 + i, 99 + i, 100.5 + i, None, None])
    bars = dr.half_day_bars(rows)
    assert [b.key for b in bars] == ["2024-01-02 AM", "2024-01-02 PM", "2024-01-03 AM"]
    am = bars[0]
    assert am.open == 100 and am.close == 100.5 + 11 and am.high == 101 + 11
    assert len(dr.daily_from_intraday(rows)) == 1


def test_features_are_lagged_and_missing_inputs_drop_rows():
    bars, vix = _garch_bars(n=60)
    rows = dr.build_rows(bars, vix=vix[:-10])
    r = rows[0]
    t = next(i for i, b in enumerate(bars) if b.key == r["key"])
    assert r["ret_next"] == pytest.approx(math.log(bars[t + 1].close / bars[t].close))
    assert r["features"]["r1"] == pytest.approx(math.log(bars[t].close / bars[t - 1].close))
    with_vix = dr.usable(rows, dr.FEATURE_SETS["price_vix"])
    assert 0 < len(with_vix) < len(rows)  # rows without VIX are dropped, not zero-filled
    assert all("vix_lvl" not in x["features"] for x in rows if x["day"] > vix[-11].day)


def test_volatility_models_beat_naive_on_garch_and_direction_shows_no_edge():
    bars, vix = _garch_bars()
    cfg = dr.WalkForwardConfig(initial_train=400, step=40)
    report = dr.run_research(nifty_daily=bars, vix=vix, cfg=cfg)
    vol = report["volatility"]
    assert vol["status"] == "EVALUATED" and vol["vix_available"]
    naive = vol["models"]["naive_rv1"]["holdout"]["qlike"]
    assert vol["models"]["har"]["holdout"]["qlike"] < naive
    assert report["summary"]["volatility"]["beats_naive_holdout"] is True
    # Returns are a driftless random walk: no direction edge may be claimed.
    assert report["summary"]["direction_edge_supported"] is False
    evaluated = [r for r in report["direction"] if r["status"] == "EVALUATED"]
    assert sum(r["model"] == "empirical_prior" for r in evaluated) == 1
    assert all(r["development"]["trials_considered"] == len(evaluated) for r in evaluated)


def test_insufficient_history_is_reported():
    bars, vix = _garch_bars(n=200)
    report = dr.run_research(nifty_daily=bars, vix=vix)
    assert report["volatility"]["status"] == "INSUFFICIENT_ROWS"
    assert all(r["status"] == "INSUFFICIENT_ROWS" for r in report["direction"])
    assert report["summary"]["direction_edge_supported"] is False


def test_direction_pipeline_detects_a_real_edge():
    """Positive control: next-day returns follow AR(1) on r1, so an edge must be found."""
    rng = np.random.default_rng(11)
    bars, price, prev_r, day0 = [], 10000.0, 0.0, date(2020, 1, 1)
    for t in range(1100):
        r = 0.35 * prev_r + 0.01 * rng.standard_normal()
        c = price * math.exp(r)
        day = (day0 + timedelta(days=t)).isoformat()
        bars.append(dr.Bar(day, day, price, max(price, c) * 1.004, min(price, c) * 0.996, c))
        price, prev_r = c, r
    report = dr.run_research(nifty_daily=bars, cfg=dr.WalkForwardConfig(initial_train=400, step=40))
    best = report["summary"]["direction_best_on_development"]
    assert best["model"] in {"logistic", "lightgbm"}
    assert report["summary"]["direction_edge_supported"] is True
    assert best["holdout_accuracy"]["p_value_vs_50pct"] < 0.05


# ------------------------------------------------------------- PCR + CLI

def test_build_pcr_history_selects_band_before_the_pcr_window(tmp_path):
    from app.market.options_history import build_pcr_history, load_pcr

    closes = {"2024-01-01": 19000.0, "2024-01-08": 22000.0}
    fetched = []

    def fetch_candles(symbol, window):
        fetched.append(symbol)
        oi = 200.0 if symbol.endswith("PE") else 100.0
        return {"payload": {"candles": [["2024-01-10 15:30:00", 1, 1, 1, 1, 0, oi]]}}

    contracts = [f"NSE-NIFTY-11Jan24-{k}-{s}" for k in (19000, 22000) for s in ("CE", "PE")]
    doc = build_pcr_history(
        list_expiries=lambda year: ["2024-01-11", "2025-01-01"],
        list_contracts=lambda exp: contracts,
        fetch_candles=fetch_candles, reference_closes=closes,
        start=date(2024, 1, 1), end=date(2024, 12, 31), strike_step=50, band_strikes=2,
        lookback_days=3, root=tmp_path, log=lambda m: None,
    )
    # cutoff 2024-01-08 -> reference 22000: only the 22000 strikes are fetched
    assert sorted(fetched) == ["NSE-NIFTY-11Jan24-22000-CE", "NSE-NIFTY-11Jan24-22000-PE"]
    assert doc["pcr"]["2024-01-10"]["pcr_oi"] == pytest.approx(2.0)
    assert load_pcr(tmp_path)["2024-01-10"]["expiry"] == "2024-01-11"


def test_research_daily_cli_writes_report(tmp_path, monkeypatch):
    from app import cli

    bars, vix = _garch_bars(n=800)
    monkeypatch.setattr(hl, "HISTORY_DIR", tmp_path)

    def save(symbol, series):
        rows = [[f"{b.day}T00:00:00+05:30", b.open, b.high, b.low, b.close, None, None] for b in series]
        hl.series_path(symbol, "1day", tmp_path).write_text(__import__("json").dumps({"candles": rows}), encoding="utf-8")

    save("NSE-NIFTY", bars)
    save("NSE-INDIAVIX", vix)
    out = tmp_path / "report.json"
    rc = cli.main(["research-daily", "--initial-train", "300", "--step", "40", "--output", str(out)])
    assert rc == 0
    report = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert report["schema"] == "daily-research-1"
    assert report["inputs"]["vix_bars"] == 800 and report["inputs"]["banknifty_bars"] == 0
    assert report["volatility"]["status"] == "EVALUATED"
