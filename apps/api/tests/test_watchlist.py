"""Watchlist outcome tracking. Offline; no provider is called."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_session_factory
from app.watchlist.service import accuracy, create_suggestion, evaluate_open, session_close
from app.market.schemas import IST
from tests.conftest import login

T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)  # 17:30 IST, Thursday


@pytest.fixture
def session(db):
    s = get_session_factory()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _obs(inst, price, at):
    return {"instrument": inst, "last_price": price, "retrieved_at": at.isoformat()}


def _add(session, opt="CE", inst="CRUDEMINI"):
    return create_suggestion(
        session, instrument=inst, contract=f"{inst} 9300 {opt}", option_type=opt, call="BUY",
        entry_spot=9300.0, target_points=50.0, stop_loss_points=25.0,
        model_premiums={"entry": 47.2}, data_class="UNVERIFIED_PROVIDER_DATA", created_by="t", now=T0,
    )


def test_levels_mirror_for_pe(session):
    ce, pe = _add(session, "CE"), _add(session, "PE")
    assert (float(ce.target_spot), float(ce.stop_loss_spot)) == (9350.0, 9275.0)
    assert (float(pe.target_spot), float(pe.stop_loss_spot)) == (9250.0, 9325.0)
    assert ce.direction == "UP" and pe.direction == "DOWN"


def test_target_and_stop_resolution(session):
    ce, pe = _add(session, "CE"), _add(session, "PE")
    evaluate_open(session, [_obs("CRUDEMINI", 9351, T0 + timedelta(minutes=5))], now=T0 + timedelta(minutes=5))
    assert ce.status == "TARGET_HIT"
    assert pe.status == "SL_HIT"
    assert float(ce.resolved_spot) == 9351


def test_stale_quote_never_resolves(session):
    ce = _add(session)
    evaluate_open(session, [_obs("CRUDEMINI", 9400, T0 - timedelta(minutes=1))], now=T0 + timedelta(minutes=1))
    assert ce.status == "OPEN" and ce.checks == 0


def test_expiry_at_session_close(session):
    ce = _add(session)
    assert ce.expires_at == datetime(2026, 10, 15, 23, 30, tzinfo=IST)
    evaluate_open(session, [_obs("CRUDEMINI", 9310, T0 + timedelta(hours=1))], now=T0 + timedelta(hours=1))
    assert ce.status == "OPEN" and float(ce.max_favorable_spot) == 9310
    evaluate_open(session, [], now=datetime(2026, 10, 15, 23, 31, tzinfo=IST))
    assert ce.status == "EXPIRED"


def test_nse_close_rolls_past_weekend():
    friday_evening = datetime(2026, 10, 16, 16, 0, tzinfo=IST)
    assert session_close("NIFTY", friday_evening) == datetime(2026, 10, 19, 15, 30, tzinfo=IST)


def test_accuracy_excludes_expired(session):
    a, b, c = _add(session, "CE"), _add(session, "CE"), _add(session, "PE")
    a.status, b.status, c.status = "TARGET_HIT", "SL_HIT", "EXPIRED"
    stats = accuracy([a, b, c])
    assert stats["overall"]["decided"] == 2
    assert stats["overall"]["hit_rate"] == 0.5
    assert stats["overall"]["EXPIRED"] == 1
    assert stats["sample_warning"] is True


def test_routes_require_auth_and_csrf(client, monkeypatch):
    monkeypatch.setattr("app.watchlist.routes.stored_observations", lambda: [])
    assert client.get("/api/watchlist").status_code == 401
    token = login(client)
    body = {"instrument": "CRUDEMINI", "contract": "CRUDEMINI 9300 CE", "option_type": "CE",
            "entry_spot": 9300, "target_points": 50, "stop_loss_points": 25}
    assert client.post("/api/watchlist", json=body).status_code == 403
    added = client.post("/api/watchlist", headers={"x-csrf-token": token}, json=body)
    assert added.status_code == 200, added.text
    listing = client.get("/api/watchlist").json()
    assert len(listing["items"]) == 1 and listing["items"][0]["status"] == "OPEN"
    sid = listing["items"][0]["suggestion_id"]
    cancelled = client.post(f"/api/watchlist/{sid}/cancel", headers={"x-csrf-token": token})
    assert cancelled.json()["item"]["status"] == "CANCELLED"
    cleared = client.post("/api/watchlist/clear", headers={"x-csrf-token": token})
    assert cleared.status_code == 200
    assert len(client.get("/api/watchlist").json()["items"]) == 0



def test_stop_is_not_cancelled_by_premium(session, monkeypatch):
    """A spot stop hit resolves as SL_HIT even if a live premium sits above the premium stop."""
    import app.market.groww_options as go

    ce = _add(session, "CE")
    ce.model_premiums = {"entry": 47.2, "target": 70.0, "stop_loss": 30.0}
    quoted = (T0 + timedelta(minutes=4)).isoformat()
    monkeypatch.setattr(go, "get_live_option_quote", lambda *a, **k: {"ltp": 45.0, "retrieved_at": quoted})
    evaluate_open(session, [_obs("CRUDEMINI", 9270, T0 + timedelta(minutes=5))], now=T0 + timedelta(minutes=5))
    assert ce.status == "SL_HIT"
    assert ce.model_premiums["exit_premium"] == 45.0


def test_premium_alone_never_resolves_target(session, monkeypatch):
    """A premium above its target does not mark TARGET_HIT while spot is inside the band."""
    import app.market.groww_options as go

    ce = _add(session, "CE")
    ce.model_premiums = {"entry": 47.2, "target": 70.0, "stop_loss": 30.0}
    quoted = (T0 + timedelta(minutes=4)).isoformat()
    monkeypatch.setattr(go, "get_live_option_quote", lambda *a, **k: {"ltp": 90.0, "retrieved_at": quoted})
    evaluate_open(session, [_obs("CRUDEMINI", 9310, T0 + timedelta(minutes=5))], now=T0 + timedelta(minutes=5))
    assert ce.status == "OPEN"
