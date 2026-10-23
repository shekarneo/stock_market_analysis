"""Kill switch wiring and the out-of-band (file / GPIO-style) halt."""

from __future__ import annotations

import pytest

from app.config.loader import load_defaults
from app.config.schemas import OperatingMode
from app.errors import ModeForbidden
from app.execution.orders import live_order_calls, request_order
from app.risk import external_halt
from app.risk.external_halt import clear_halt_file, external_halt_status, trip_halt_file
from app.risk.gates import evaluate
from app.settings import REPO_ROOT

RISK = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk


@pytest.fixture
def halt_env(tmp_path, monkeypatch):
    monkeypatch.setenv(external_halt.HALT_FILE_ENV, str(tmp_path / "HALT"))
    monkeypatch.delenv(external_halt.GPIO_PATH_ENV, raising=False)
    monkeypatch.delenv(external_halt.GPIO_ACTIVE_ENV, raising=False)
    return tmp_path


def _entry():
    return {"mode": "PAPER", "intent_purpose": "ENTRY", "underlying": "NIFTY", "option_type": "CE", "side": "BUY"}


def test_clear_by_default(halt_env):
    assert external_halt_status()["halted"] is False


def test_halt_file_halts_and_clears(halt_env):
    path = trip_halt_file("maintenance window", actor="test")
    status = external_halt_status()
    assert status["halted"] is True and "HALT_FILE_PRESENT" in status["reasons"]
    assert "maintenance window" in status["note"]
    assert path.exists()
    assert clear_halt_file() is True
    assert external_halt_status()["halted"] is False
    assert clear_halt_file() is False


def test_trip_requires_a_reason(halt_env):
    with pytest.raises(ValueError):
        trip_halt_file("  ")


def test_gpio_input_active_and_inactive(halt_env, monkeypatch):
    gpio = halt_env / "gpio17_value"
    monkeypatch.setenv(external_halt.GPIO_PATH_ENV, str(gpio))
    gpio.write_text("0\n", encoding="utf-8")
    assert external_halt_status()["halted"] is False
    gpio.write_text("1\n", encoding="utf-8")
    status = external_halt_status()
    assert status["halted"] is True and "HALT_GPIO_ACTIVE" in status["reasons"]


def test_active_low_gpio(halt_env, monkeypatch):
    gpio = halt_env / "gpio_value"
    monkeypatch.setenv(external_halt.GPIO_PATH_ENV, str(gpio))
    monkeypatch.setenv(external_halt.GPIO_ACTIVE_ENV, "0")
    gpio.write_text("0", encoding="utf-8")
    assert external_halt_status()["halted"] is True


def test_unreadable_gpio_fails_closed(halt_env, monkeypatch):
    monkeypatch.setenv(external_halt.GPIO_PATH_ENV, str(halt_env / "missing" / "value"))
    status = external_halt_status()
    assert status["halted"] is True and "HALT_GPIO_UNREADABLE" in status["reasons"]


def test_gate_vetoes_entries_without_any_database(halt_env):
    trip_halt_file("test", actor="test")
    result = evaluate(_entry(), session=None, config=RISK)
    gate = next(g for g in result["gates"] if g["name"] == "kill_switch")
    assert gate["detail"] == "EXTERNAL_HALT" and gate["blocks"] is True
    assert "EXTERNAL_HALT" in result["reasons"]


def test_gate_never_blocks_exits(halt_env):
    trip_halt_file("test", actor="test")
    exit_intent = {**_entry(), "intent_purpose": "EXIT", "side": "SELL"}
    gate = next(g for g in evaluate(exit_intent, session=None, config=RISK)["gates"] if g["name"] == "kill_switch")
    assert gate["blocks"] is False


def test_live_order_path_refuses_while_halted(halt_env):
    trip_halt_file("test", actor="test")
    live_order_calls.clear()
    with pytest.raises(ModeForbidden, match="out-of-band"):
        request_order(OperatingMode.LIVE_TRADING, {}, live_trading_enabled=True, server_flag=True)
    assert live_order_calls == []


# --- API (Postgres test fixture) ------------------------------------------------------

def test_kill_switch_api_trips_and_reports(client, halt_env):
    from tests.conftest import login

    unauth = client.get("/api/kill-switch")
    assert unauth.status_code in {401, 403}
    token = login(client)
    headers = {"x-csrf-token": token}
    state = client.get("/api/kill-switch").json()
    assert state["kill_switch"] is False and state["entries_halted"] is False

    tripped = client.post("/api/kill-switch", json={"enabled": True, "reason": "ui emergency"}, headers=headers).json()
    assert tripped["kill_switch"] is True and tripped["entries_halted"] is True

    trip_halt_file("out of band", actor="test")
    cleared = client.post("/api/kill-switch", json={"enabled": False, "reason": "reset"}, headers=headers).json()
    assert cleared["kill_switch"] is False
    assert cleared["entries_halted"] is True  # the out-of-band halt is not cleared by the API
    assert client.get("/health").json()["external_halt"]["halted"] is True
