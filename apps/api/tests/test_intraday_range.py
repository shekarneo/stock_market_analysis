"""Rest-of-day range: walk-forward evaluation, live bands from the quote, and honest refusals."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from app.research import daily_research as dr
from app.research import intraday_range as ir
from app.research import multiyear_service as svc

IST = timezone(timedelta(hours=5, minutes=30))


def _market(n_days: int, seed: int = 3) -> tuple[list[list], list[list], list[list]]:
    """15m bars, daily candles and a VIX that tracks persistent (log-AR(1)) daily volatility."""
    rng = np.random.default_rng(seed)
    rows15, daily, vix = [], [], []
    price, log_sig, day = 20000.0, math.log(0.010), date(2021, 1, 4)
    while len(daily) < n_days:
        if day.weekday() < 5:
            log_sig = math.log(0.010) + 0.9 * (log_sig - math.log(0.010)) + 0.25 * rng.standard_normal()
            sig = math.exp(log_sig) / math.sqrt(ir.SESSION_BARS)
            open_ = price * (1 + 0.3 * sig * rng.standard_normal())
            o, bars = open_, []
            for i in range(ir.SESSION_BARS):
                c = o * (1 + sig * rng.standard_normal())
                h, lo = max(o, c) * (1 + abs(0.4 * sig * rng.standard_normal())), min(o, c) * (1 - abs(0.4 * sig * rng.standard_normal()))
                start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=15 * i)
                bars.append([start.isoformat(), o, h, lo, c, None])
                o = c
            rows15.extend(bars)
            stamp = f"{day.isoformat()}T00:00:00+05:30"
            daily.append([stamp, bars[0][1], max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4], None])
            v = 100 * math.exp(log_sig) * math.sqrt(248) * (1 + 0.05 * rng.standard_normal())
            vix.append([stamp, v, v, v, v, None])
            price = bars[-1][4]
        day += timedelta(days=1)
    return rows15, daily, vix


@pytest.fixture(scope="module")
def model():
    rows15, daily, vix = _market(560)
    rows = ir.build_rows(rows15, dr.daily_bars(daily), dr.daily_bars(vix))
    assert {r["k"] for r in rows} == set(ir.CHECKPOINTS)
    return ir.evaluate(rows, cfg=dr.WalkForwardConfig(initial_train=300, step=40))


def test_sessions_must_be_complete():
    rows15, _, _ = _market(3)
    assert len(ir.sessions_15m(rows15)) == 3
    assert len(ir.sessions_15m(rows15[:-1])) == 2  # a session missing its 15:15 bar is not used


def test_evaluation_beats_simple_rules_and_bands_hold(model):
    assert model["status"] == "EVALUATED"
    assert model["selected_on_development"] not in ir.SCALED
    assert model["holdout_mse_improvement_pct"]["naive_prev_day"] > 0
    assert set(model["dm_holdout"]) == {"naive_prev_day", "so_far_scaled"}
    cov = model["holdout_coverage_mean"]
    assert 0.80 <= cov["range_band90"] <= 0.98 and 0.55 <= cov["range_band68"] <= 0.80
    assert set(model["checkpoints"]) == {str(k) for k in ir.CHECKPOINTS}
    assert model["checkpoints"]["1"]["time"] == "09:30" and model["checkpoints"]["24"]["time"] == "15:15"


def test_too_little_history_is_reported_not_guessed():
    rows15, daily, vix = _market(120)
    out = ir.evaluate(ir.build_rows(rows15, dr.daily_bars(daily), dr.daily_bars(vix)))
    assert out["status"] == "INSUFFICIENT_SESSIONS"


def test_live_bands_are_ordered_around_the_price(model):
    ctx = ir.Context(prev_close=22687.65, log_rv1=math.log(0.015), log_rv5=math.log(0.014),
                     log_rv22=math.log(0.013), log_vix=math.log(16.0))
    f = ir.forecast_from_quote(model, ctx=ctx, k=12, open_=22742.2, high=22787.25, low=22372.0, price=22450.0)
    assert f["status"] == "OK" and f["checkpoint"] == "12:15"
    assert f["low_by_close"]["p90"] < f["low_by_close"]["p68"] < 22450.0 < f["high_by_close"]["p68"] < f["high_by_close"]["p90"]
    lo90, hi90 = f["close_band90"]
    assert lo90 < f["close_band68"][0] < f["close_band68"][1] < hi90
    assert f["remaining_range_band90_pct"][0] < f["expected_remaining_range_pct"] < f["remaining_range_band90_pct"][1]
    missing = ir.forecast_from_quote(model, ctx=ir.Context(22687.65, -4.0, -4.0, -4.0, None), k=12,
                                     open_=22742.2, high=22787.25, low=22372.0, price=22450.0)
    if model["selected_on_development"] == "har_intraday_vix":
        assert missing["status"] == "MISSING_INPUTS" and missing["missing"] == ["log_vix"]


# ------------------------------------------------------------------------------ live service

def _history(monkeypatch, daily, vix):
    docs = {("NSE-NIFTY", "1day"): {"candles": daily}, ("NSE-INDIAVIX", "1day"): {"candles": vix}}
    monkeypatch.setattr(svc.hl, "load_series", lambda symbol, interval, root=None: docs.get((symbol, interval)))


def _quote(now: datetime, *, price: float, ohlc: dict) -> list[dict]:
    return [{"instrument": "NIFTY", "last_price": price, "ohlc": ohlc,
             "retrieved_at": (now - timedelta(seconds=10)).astimezone(timezone.utc).isoformat()}]


@pytest.fixture()
def live(model, monkeypatch):
    _, daily, vix = _market(60, seed=9)
    _history(monkeypatch, daily, vix)
    last = daily[-1]
    d = date.fromisoformat(last[0][:10]) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    now = datetime(d.year, d.month, d.day, 12, 20, tzinfo=IST)
    prev_close = last[4]
    ohlc = {"open": prev_close * 1.001, "high": prev_close * 1.006, "low": prev_close * 0.995, "close": prev_close}
    return {"now": now, "last": last, "ohlc": ohlc, "price": prev_close * 1.002, "model": model}


def test_live_forecast_from_the_stored_quote(live):
    f = svc.live_intraday_forecast(now=live["now"], model=live["model"],
                                   observations=_quote(live["now"], price=live["price"], ohlc=live["ohlc"]))
    assert f["status"] == "OK" and f["checkpoint"] == "12:15"  # 12:20 uses the model for 12:15
    assert f["quote"]["last_price"] == live["price"] and f["model"]["sessions"] == live["model"]["sessions"]


@pytest.mark.parametrize(("case", "status"), [
    ("no_model", "MODEL_MISSING"), ("saturday", "MARKET_CLOSED"), ("after_close", "MARKET_CLOSED"),
    ("pre_open", "PRE_OPEN"), ("no_quote", "NO_LIVE_QUOTE"), ("stale", "STALE_QUOTE"),
    ("history_behind", "HISTORY_BEHIND"), ("holiday", "NO_SESSION_TODAY"),
])
def test_live_forecast_refuses_instead_of_guessing(live, case, status):
    now, model, ohlc, price = live["now"], live["model"], dict(live["ohlc"]), live["price"]
    obs = None
    if case == "no_model":
        model = {"status": "INSUFFICIENT_SESSIONS"}
    elif case == "saturday":
        now = now + timedelta(days=(5 - now.weekday()) % 7)
    elif case == "after_close":
        now = now.replace(hour=15, minute=40)
    elif case == "pre_open":
        now = now.replace(hour=9, minute=20)
    elif case == "no_quote":
        obs = [{"instrument": "NIFTY", "last_price": price, "ohlc": None, "retrieved_at": now.isoformat()}]
    elif case == "stale":
        obs = _quote(now - timedelta(minutes=10), price=price, ohlc=ohlc)
    elif case == "history_behind":
        ohlc["close"] = ohlc["close"] * 1.01  # Groww's previous close is a session the saved history lacks
    elif case == "holiday":
        last = live["last"]
        ohlc = {"open": last[1], "high": last[2], "low": last[3], "close": 1.0}
        price = last[4]
    obs = obs if obs is not None else _quote(now, price=price, ohlc=ohlc)
    out = svc.live_intraday_forecast(now=now, model=model, observations=obs)
    assert out["status"] == status
    assert "high_by_close" not in out


def test_each_index_uses_its_own_history_and_quote(model, monkeypatch):
    _, nifty, vix = _market(60, seed=9)
    _, bank, _ = _market(60, seed=11)
    bank = [[r[0], *(v * 2.4 for v in r[1:5]), None] for r in bank]  # a different index level and path
    docs = {("NSE-NIFTY", "1day"): {"candles": nifty}, ("NSE-BANKNIFTY", "1day"): {"candles": bank},
            ("NSE-INDIAVIX", "1day"): {"candles": vix}}
    monkeypatch.setattr(svc.hl, "load_series", lambda symbol, interval, root=None: docs.get((symbol, interval)))
    d = date.fromisoformat(bank[-1][0][:10]) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    now = datetime(d.year, d.month, d.day, 11, 5, tzinfo=IST)
    pc = bank[-1][4]
    ohlc = {"open": pc * 1.001, "high": pc * 1.004, "low": pc * 0.996, "close": pc}
    obs = [{"instrument": "BANKNIFTY", "last_price": pc * 1.002, "ohlc": ohlc,
            "retrieved_at": (now - timedelta(seconds=5)).isoformat()}]
    f = svc.live_intraday_forecast("BANKNIFTY", now=now, model=model, observations=obs)
    assert f["status"] == "OK" and f["instrument"] == "BANKNIFTY" and f["checkpoint"] == "11:00"
    # A NIFTY quote never stands in for BANKNIFTY
    nifty_only = [{**obs[0], "instrument": "NIFTY"}]
    assert svc.live_intraday_forecast("BANKNIFTY", now=now, model=model, observations=nifty_only)["status"] == "NO_LIVE_QUOTE"
    # No SENSEX history saved: reported, not borrowed from another index
    sx = [{**obs[0], "instrument": "SENSEX"}]
    assert svc.live_intraday_forecast("SENSEX", now=now, model=model, observations=sx)["status"] == "HISTORY_MISSING"


def test_run_intraday_ranges_reports_missing_history(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "INTRADAY_MODEL_DIR", tmp_path)
    rows15, daily, vix = _market(560)
    docs = {("NSE-NIFTY", "15minute"): {"candles": rows15}, ("NSE-NIFTY", "1day"): {"candles": daily},
            ("NSE-INDIAVIX", "1day"): {"candles": vix}}
    monkeypatch.setattr(svc.hl, "load_series", lambda symbol, interval, root=None: docs.get((symbol, interval)))
    monkeypatch.setattr(svc, "completed_sessions", lambda rows, now=None: rows)
    out = svc.run_intraday_ranges(log=lambda m: None)
    assert out["NIFTY"]["status"] in ("EVALUATED", "INSUFFICIENT_SESSIONS")
    assert out["BANKNIFTY"]["status"] == "NO_HISTORY" and out["SENSEX"]["status"] == "NO_HISTORY"
    assert svc.load_intraday_model("NIFTY")["instrument"] == "NIFTY"
    assert svc.load_intraday_model("BANKNIFTY") is None


def test_intraday_endpoint(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research import multiyear_routes as routes

    seen = []

    def fake(instrument):
        seen.append(instrument)
        return {"status": "MARKET_CLOSED", "value": float("nan")}

    monkeypatch.setattr(svc, "live_intraday_forecast", fake)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._settings] = lambda: None
    monkeypatch.setattr(routes, "read_session", lambda request, settings: {"username": "op"})
    client = TestClient(app)
    body = client.get("/api/research/intraday-range").json()
    assert body == {"status": "MARKET_CLOSED", "value": None}  # NaN is reported as null, never as a number
    assert client.get("/api/research/intraday-range?instrument=SENSEX").status_code == 200
    assert client.get("/api/research/intraday-range?instrument=CRUDE").status_code == 422  # no MCX history: no model
    assert seen == ["NIFTY", "SENSEX"]
