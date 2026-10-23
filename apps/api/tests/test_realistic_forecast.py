"""Tuned next-session forecast: calibrated ranges, honest direction, real-data retrain sources."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from app.research import daily_research as dr
from app.research import realistic_forecast as rf
from tests.test_research_multiyear import _garch_bars

CFG = dr.WalkForwardConfig(initial_train=400, step=40)
SMALL_GRID = [rf._logistic_spec(1.0), rf._lightgbm_spec(100, 50)]


@pytest.fixture(autouse=True)
def _small_grid(monkeypatch):
    monkeypatch.setattr(rf, "DIRECTION_GRID", SMALL_GRID)


def test_latest_features_match_build_rows():
    bars, vix = _garch_bars(n=80)
    rows = dr.build_rows(bars, vix=vix)
    latest = dr.latest_features(bars, vix=vix)
    assert latest["day"] == bars[-1].day and latest["close"] == bars[-1].close
    # The last training row is bar -2; its features equal latest_features computed one bar earlier
    assert rows[-1]["day"] == bars[-2].day
    assert dr.latest_features(bars[:-1], vix=vix[:-1])["features"] == pytest.approx(rows[-1]["features"])


def test_range_forecast_is_calibrated_and_direction_is_honest_on_random_walk():
    bars, vix = _garch_bars(n=1100)
    report = rf.build_forecast(nifty_daily=bars, nifty_half_day=None, vix=vix, banknifty=None, sensex=None, cfg=CFG)
    rng = report["range"]
    assert rng["status"] == "OK" and rng["model"] != "naive_rv1"
    lo, hi = rng["range_band90_pct"]
    assert lo < rng["expected_range_pct"] < hi
    # Bands come from development errors; on the unseen holdout they must roughly hold
    assert 0.80 <= rng["holdout_band_coverage"]["band90"] <= 0.98
    assert 0.55 <= rng["holdout_band_coverage"]["band68"] <= 0.80
    assert rng["holdout_qlike_improvement_vs_naive_pct"] > 0
    d = report["direction_next_session"]
    assert d["status"] == "NO_RELIABLE_EDGE"
    assert d["probability_up"] == pytest.approx(d["historical_up_rate"])
    assert report["for_session"] == rf.next_weekday(report["as_of_session"])


def test_predictable_direction_is_published():
    rng_ = np.random.default_rng(11)
    bars, price, prev_r, day0 = [], 10000.0, 0.0, date(2020, 1, 1)
    vix = []
    for t in range(1100):
        r = 0.35 * prev_r + 0.01 * rng_.standard_normal()
        c = price * math.exp(r)
        day = (day0 + timedelta(days=t)).isoformat()
        bars.append(dr.Bar(day, day, price, max(price, c) * 1.004, min(price, c) * 0.996, c))
        vix.append(dr.Bar(day, day, 15.0, 15.0, 15.0, 15.0))
        price, prev_r = c, r
    report = rf.build_forecast(nifty_daily=bars, nifty_half_day=None, vix=vix, banknifty=None, sensex=None, cfg=CFG)
    d = report["direction_next_session"]
    assert d["status"] == "EDGE_SUPPORTED"
    assert 0.0 < d["probability_up"] < 1.0
    expected_up = report["direction_next_session"]["probability_up"] > 0.5
    assert expected_up == (math.log(bars[-1].close / bars[-2].close) > 0)  # AR(1): sign follows the last return


def test_next_weekday_skips_weekends():
    assert rf.next_weekday("2026-10-23") == "2026-10-26"  # Friday -> Monday
    assert rf.next_weekday("2026-10-21") == "2026-10-22"


# ------------------------------------------------------------------------- API

def test_forecast_endpoint(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from app.errors import AppError
    from app.research import multiyear_routes as routes
    from app.research import multiyear_service as svc

    monkeypatch.setattr(svc, "FORECAST_PATH", tmp_path / "f.json")
    monkeypatch.setattr(routes, "read_session", lambda request, settings: {"username": "op"})
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(AppError)
    def handle(_r, exc):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code})

    app.dependency_overrides[routes._settings] = lambda: None
    client = TestClient(app)
    assert client.get("/api/research/multiyear/forecast").json()["code"] == "FORECAST_MISSING"
    (tmp_path / "f.json").write_text(json.dumps({"schema": "realistic-forecast-1", "range": {"x": float("nan")}}).replace("NaN", "NaN"))
    body = client.get("/api/research/multiyear/forecast").json()
    assert body["schema"] == "realistic-forecast-1" and body["range"]["x"] is None
