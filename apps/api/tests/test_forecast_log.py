"""Forecast log: what the cards said is recorded before the outcome and scored after the close."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.research import forecast_log as fl

IST = timezone(timedelta(hours=5, minutes=30))


def _daily_forecast(for_session="2026-10-26", as_of="2026-10-23"):
    return {"instrument": "NIFTY", "for_session": for_session, "as_of_session": as_of, "last_close": 22600.0,
            "range": {"status": "OK", "expected_range_pct": 2.07, "range_band68_pct": [1.33, 3.15],
                      "range_band90_pct": [1.0, 4.44], "close_move_p90_pct": 2.63},
            "direction_next_session": {"status": "NO_RELIABLE_EDGE", "probability_up": 0.54}}


def _intraday_forecast(checkpoint="12:15", price=22444.0):
    return {"status": "OK", "checkpoint": checkpoint, "price": price, "expected_remaining_range_pct": 0.82,
            "remaining_range_band68_pct": [0.55, 1.2], "remaining_range_band90_pct": [0.4, 1.6],
            "high_by_close": {"p68": 22555.0, "p90": 22653.0}, "low_by_close": {"p68": 22327.0, "p90": 22222.0},
            "close_band68": [22326.0, 22561.0], "close_band90": [22250.0, 22640.0], "model": {"last": "2026-10-23"}}


def test_daily_forecast_is_logged_once_and_only_before_its_session(tmp_path):
    path = tmp_path / "log.jsonl"
    evening = datetime(2026, 10, 23, 18, 0, tzinfo=IST)
    assert fl.record_daily(_daily_forecast(), now=evening, path=path)["for_session"] == "2026-10-26"
    assert fl.record_daily(_daily_forecast(), now=evening + timedelta(hours=1), path=path) is None  # a rebuild is not a second forecast
    late = datetime(2026, 10, 27, 10, 0, tzinfo=IST)
    assert fl.record_daily(_daily_forecast("2026-10-27", "2026-10-26"), now=late, path=path) is None  # session already open
    assert fl.record_daily({**_daily_forecast("2026-10-28"), "range": {"status": "MISSING_INPUTS"}}, path=path) is None
    assert len(fl._read(path)) == 1


def test_intraday_is_logged_near_its_checkpoint_once(tmp_path):
    path = tmp_path / "log.jsonl"
    at = datetime(2026, 10, 23, 12, 15, 20, tzinfo=IST)
    assert fl.record_intraday("NIFTY", _intraday_forecast(), now=at, path=path) is not None
    assert fl.record_intraday("NIFTY", _intraday_forecast(), now=at + timedelta(seconds=15), path=path) is None
    # Logged 4 minutes late, the price is not the checkpoint price: skipped, not mislabelled
    assert fl.record_intraday("NIFTY", _intraday_forecast("12:30"), now=datetime(2026, 10, 23, 12, 34, tzinfo=IST), path=path) is None
    assert fl.record_intraday("BANKNIFTY", {"status": "MARKET_CLOSED"}, now=at, path=path) is None
    assert [r["instrument"] for r in fl._read(path)] == ["NIFTY"]


def _bars(day: str, closes: list[float]) -> list[list]:
    start = datetime.fromisoformat(f"{day}T09:15:00+05:30")
    return [[(start + timedelta(minutes=15 * i)).isoformat(), c, c + 20, c - 20, c, None] for i, c in enumerate(closes)]


def test_scoring_uses_completed_sessions_and_never_rescores(tmp_path):
    path = tmp_path / "log.jsonl"
    fl.record_daily(_daily_forecast(), now=datetime(2026, 10, 23, 18, 0, tzinfo=IST), path=path)
    fl.record_intraday("NIFTY", _intraday_forecast(), now=datetime(2026, 10, 26, 12, 15, 5, tzinfo=IST), path=path)
    # Nothing saved for 26-Oct yet: both stay pending
    assert fl.score_pending({}, {}, path=path) == {"records": 2, "newly_scored": 0, "pending": 2}
    day_bar = ["2026-10-26T00:00:00+05:30", 22610.0, 22800.0, 22370.0, 22753.0]  # 1.92% range, inside 68%
    closes = [22450.0] * 12 + [22444.0 + 10 * i for i in range(13)]       # rises from the 12:15 bar
    out = fl.score_pending({"NIFTY": {"2026-10-26": day_bar}}, {"NIFTY": {"2026-10-26": _bars("2026-10-26", closes)}}, path=path)
    assert out["newly_scored"] == 2 and out["pending"] == 0
    daily, intra = fl._read(path)
    assert daily["outcome"]["in_band68"] is True and daily["outcome"]["up"] is True
    assert intra["outcome"]["high"] == pytest.approx(22564.0 + 20) and intra["outcome"]["high_within_p90"] is True
    assert intra["outcome"]["close"] == 22564.0 and intra["outcome"]["close_in_band68"] is False
    # An incomplete session is not a result
    fl.record_intraday("NIFTY", _intraday_forecast(), now=datetime(2026, 10, 27, 12, 15, 5, tzinfo=IST), path=path)
    assert fl.score_pending({}, {"NIFTY": {"2026-10-27": _bars("2026-10-27", [22500.0] * 20)}}, path=path)["newly_scored"] == 0
    assert fl.score_pending({"NIFTY": {"2026-10-26": day_bar}}, {}, path=path)["newly_scored"] == 0  # scored once


def test_summary(tmp_path):
    path = tmp_path / "log.jsonl"
    fl.record_daily(_daily_forecast(), now=datetime(2026, 10, 23, 18, 0, tzinfo=IST), path=path)
    for minute in (15, 30):
        fl.record_intraday("SENSEX", _intraday_forecast(f"12:{minute}"), now=datetime(2026, 10, 26, 12, minute, 5, tzinfo=IST), path=path)
    s = fl.summarize(path)
    assert s["daily"]["logged"] == 1 and s["daily"]["scored"] == 0 and s["daily"]["range_in_band90"] is None
    sx = s["intraday"]["SENSEX"]
    assert sx["logged"] == 2 and sx["sessions"] == 1 and sx["scored"] == 0 and sx["typical_size_error_factor"] is None
    assert sx["recent_sessions"][0] == {"day": "2026-10-26", "checkpoints": 2, "scored": 0,
                                         "range_in_band90": None, "high_within_p90": None, "low_within_p90": None}


def test_poller_logging_uses_the_live_forecast(monkeypatch, tmp_path):
    from app.research import multiyear_service as svc

    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(svc, "live_intraday_forecast",
                        lambda instrument, now=None: _intraday_forecast() if instrument == "NIFTY" else {"status": "NO_LIVE_QUOTE"})
    rows = fl.log_live_intraday(now=datetime(2026, 10, 28, 12, 15, 40, tzinfo=IST), path=path)
    assert [r["instrument"] for r in rows] == ["NIFTY"] and rows[0]["session_day"] == "2026-10-28"


def test_track_record_endpoint(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research import multiyear_routes as routes

    monkeypatch.setattr(fl, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(routes, "read_session", lambda request, settings: {"username": "op"})
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._settings] = lambda: None
    body = TestClient(app).get("/api/research/forecast-track-record").json()
    assert body["daily"]["logged"] == 0 and body["intraday"] == {} and body["first_record"] is None
