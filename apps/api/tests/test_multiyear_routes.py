"""Multi-year research API: inventory, background jobs, report, validation.

Runs the router in a minimal app with auth stubbed (no Postgres needed).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.errors import AppError
from app.market import history_loader as hl
from app.research import multiyear_routes as routes
from app.research import multiyear_service as svc
from tests.test_research_multiyear import _garch_bars


class _Session:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(svc, "REPORT_PATH", tmp_path / "report.json")
    # Jobs also write the forecast, the agent backtest and the scorecard: keep them out of var/
    monkeypatch.setattr(svc, "FORECAST_PATH", tmp_path / "forecast.json")
    monkeypatch.setattr(svc, "INTRADAY_MODEL_DIR", tmp_path / "intraday_range")
    monkeypatch.setattr("app.analysis.track_record.BACKTEST_PATH", tmp_path / "agent_backtest.json")
    monkeypatch.setattr("app.analysis.agent_scorecard.SCORECARD_PATH", tmp_path / "agent_calls.jsonl")
    monkeypatch.setattr("app.market.options_history.OPTIONS_DIR", tmp_path / "history" / "options")
    monkeypatch.setattr(routes, "read_session", lambda request, settings: {"username": "op"})
    monkeypatch.setattr(routes, "require_csrf", lambda request, settings: {"username": "op"})
    monkeypatch.setattr(routes, "_spawn", lambda target: target())  # run jobs inline
    monkeypatch.setattr(routes, "_job", None)
    session = _Session()
    app = FastAPI()
    app.include_router(routes.router)

    @app.exception_handler(AppError)
    def handle(_request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    app.dependency_overrides[routes.get_db] = lambda: session
    app.dependency_overrides[routes._settings] = lambda: None
    client = TestClient(app)
    client.session_stub = session
    return client


def _save_series(root, symbol, bars):
    rows = [[f"{b.day}T00:00:00+05:30", b.open, b.high, b.low, b.close, None, None] for b in bars]
    path = hl.series_path(symbol, "1day", root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candles": rows, "candle_count": len(rows), "first": rows[0][0],
                                "last": rows[-1][0], "failed_windows": 0, "rejected_rows": 0}), encoding="utf-8")


def test_empty_state(api):
    body = api.get("/api/research/multiyear").json()
    assert body["report"] is None and body["job"] is None and body["pcr"] is None
    assert len(body["series"]) == 8 and not any(s["saved"] for s in body["series"])
    assert api.get("/api/research/multiyear/report").status_code == 404


def test_research_job_runs_and_report_is_served(api):
    bars, vix = _garch_bars(n=800)
    _save_series(hl.HISTORY_DIR, "NSE-NIFTY", bars)
    _save_series(hl.HISTORY_DIR, "NSE-INDIAVIX", vix)
    started = api.post("/api/research/multiyear/run", json={"initial_train": 300, "step": 40}).json()
    assert started["job"]["kind"] == "research"
    state = api.get("/api/research/multiyear").json()
    assert state["job"]["status"] == "SUCCEEDED", state["job"]
    assert state["report"]["inputs"]["vix_bars"] == 800
    assert next(s for s in state["series"] if s["name"] == "NIFTY" and s["interval"] == "1day")["candle_count"] == 800
    report = api.get("/api/research/multiyear/report").json()
    assert report["volatility"]["status"] == "EVALUATED"
    assert api.session_stub.added[-1].action == "research.multiyear.run"


def test_research_without_history_fails_visibly(api):
    api.post("/api/research/multiyear/run", json={})
    job = api.get("/api/research/multiyear").json()["job"]
    assert job["status"] == "FAILED" and "No NIFTY history" in job["error"]


def test_fetch_job_uses_service_and_validates(api, monkeypatch):
    calls = {}

    def fake_fetch(**kwargs):
        calls.update(kwargs)
        kwargs["log"]("fetched")
        return {"series": [], "failed_windows": 0, "pcr": None}

    monkeypatch.setattr(svc, "fetch_history", fake_fetch)
    monkeypatch.setattr("app.integrations.service.groww_read_token", lambda db, settings: "tok")
    monkeypatch.setattr(routes, "get_session_factory", lambda: (lambda: type("S", (), {"close": lambda self: None})()))
    body = {"symbols": ["NIFTY", "INDIAVIX"], "intervals": ["1day"], "start": "2020-01-01", "end": "2021-01-01"}
    assert api.post("/api/research/multiyear/fetch", json=body).status_code == 200
    job = api.get("/api/research/multiyear").json()["job"]
    assert job["status"] == "SUCCEEDED" and "fetched" in job["log"]
    assert any(line.startswith("Agent scorecard:") for line in job["log"])  # a NIFTY 1day fetch scores pending calls
    assert job["log"][-1].startswith("Forecast log:")  # and the logged forecasts
    assert job["result"]["scorecard_scoring"] == {"records": 0, "newly_scored": 0, "pending": 0}
    assert job["result"]["forecast_log_scoring"] == {"records": 0, "newly_scored": 0, "pending": 0}
    assert calls["token"] == "tok" and calls["symbols"] == ["NIFTY", "INDIAVIX"]
    assert api.session_stub.added[-1].action == "research.multiyear.fetch"

    # The end date is inclusive: fetching just one day (e.g. today) is allowed
    assert api.post("/api/research/multiyear/fetch", json={**body, "start": "2021-01-01", "end": "2021-01-01"}).status_code == 200
    assert calls["end"] - calls["start"] == timedelta(days=1)
    assert api.post("/api/research/multiyear/fetch", json={**body, "start": "2019-06-01"}).status_code == 422
    assert api.post("/api/research/multiyear/fetch", json={**body, "end": "2019-12-01", "start": "2020-02-01"}).status_code == 422
    assert api.post("/api/research/multiyear/fetch", json={**body, "symbols": ["CRUDE"]}).status_code == 422
    assert api.post("/api/research/multiyear/fetch", json={**body, "symbols": ["SENSEX"], "options": True}).json()["code"] == "PCR_NEEDS_NIFTY_DAILY"


def test_only_one_job_at_a_time(api, monkeypatch):
    monkeypatch.setattr(routes, "_spawn", lambda target: None)  # leave the job RUNNING
    assert api.post("/api/research/multiyear/run", json={}).status_code == 200
    second = api.post("/api/research/multiyear/run", json={})
    assert second.status_code == 409 and second.json()["code"] == "RESEARCH_JOB_RUNNING"


def test_non_finite_metrics_are_served_as_null():
    assert routes._finite({"a": float("nan"), "b": [float("inf"), 1.5], "c": "x"}) == {"a": None, "b": [None, 1.5], "c": "x"}


def test_forming_session_is_excluded_until_close():
    from datetime import datetime

    rows = [["2026-10-22T00:00:00+05:30", 1, 1, 1, 1], ["2026-10-23T00:00:00+05:30", 1, 1, 1, 1]]
    midday = datetime(2026, 10, 23, 12, 5, tzinfo=hl.IST)
    after_close = datetime(2026, 10, 23, 16, 0, tzinfo=hl.IST)
    assert [r[0][:10] for r in svc.completed_sessions(rows, midday)] == ["2026-10-22"]
    assert len(svc.completed_sessions(rows, after_close)) == 2
