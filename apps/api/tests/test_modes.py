from __future__ import annotations

from app.config.schemas import OperatingMode
from app.errors import LiveOrderDisabled, ModeForbidden
from app.execution.orders import live_order_calls, request_order
from tests.conftest import login


def test_paper_does_not_call_live_broker_order():
    live_order_calls.clear()
    with pytest_raises(ModeForbidden):
        request_order(
            OperatingMode.PAPER,
            {"note": "paper"},
            live_trading_enabled=False,
            server_flag=False,
        )
    assert live_order_calls == []


def test_replay_and_read_only_do_not_call_live_broker_order():
    live_order_calls.clear()
    for mode in (OperatingMode.REPLAY, OperatingMode.LIVE_READ_ONLY):
        with pytest_raises(ModeForbidden):
            request_order(
                mode,
                {"note": mode.value},
                live_trading_enabled=False,
                server_flag=True,
            )
    assert live_order_calls == []


def test_live_flag_without_server_flag_does_not_call_broker():
    live_order_calls.clear()
    with pytest_raises(ModeForbidden):
        request_order(
            OperatingMode.LIVE_TRADING,
            {"note": "blocked"},
            live_trading_enabled=True,
            server_flag=False,
        )
    assert live_order_calls == []


def test_fully_flagged_live_request_still_does_not_place(monkeypatch):
    live_order_calls.clear()
    with pytest_raises(LiveOrderDisabled):
        request_order(
            OperatingMode.LIVE_TRADING,
            {"note": "not-placed"},
            live_trading_enabled=True,
            server_flag=True,
        )
    assert len(live_order_calls) == 1
    assert "groww" not in str(live_order_calls).lower()


def test_http_paper_mode_cannot_call_live_order(client):
    live_order_calls.clear()
    token = login(client)
    health = client.get("/health")
    assert health.json()["mode"] == "PAPER"
    assert health.json()["live_order_server_flag"] is False
    response = client.post("/api/orders/live", json={"note": "paper"}, headers={"x-csrf-token": token})
    assert response.status_code == 403
    assert response.json()["code"] == "MODE_FORBIDDEN"
    assert live_order_calls == []


def test_switching_to_live_trading_is_rejected_by_default(client):
    token = login(client)
    response = client.put(
        "/api/config/runtime",
        json={"mode": "LIVE_TRADING", "live_trading_enabled": True, "unattended_orders": False},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "MODE_FORBIDDEN"
    current = client.get("/api/config")
    assert current.json()["document"]["runtime"]["mode"] == "PAPER"
    assert live_order_calls == []


def pytest_raises(error):
    import pytest

    return pytest.raises(error)
