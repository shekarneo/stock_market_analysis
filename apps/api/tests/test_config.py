from __future__ import annotations

from app.config.loader import load_defaults
from app.config.schemas import OperatingMode
from app.settings import get_settings
from tests.conftest import login


def test_defaults_are_paper_with_live_orders_off():
    document = load_defaults(get_settings().defaults_path)
    assert document.runtime.mode is OperatingMode.PAPER
    assert document.runtime.live_trading_enabled is False
    assert document.runtime.unattended_orders is False
    assert document.sources == []
    assert document.risk.allowed_structures == ["LONG_CE", "LONG_PE"]
    assert document.risk.allowed_underlyings == ["NIFTY", "SENSEX", "CRUDEOILMINI"]
    assert document.risk.max_futures_lots_per_trade == 1
    assert document.horizons.threshold_grid == []


def test_invalid_config_write_is_rejected(client):
    token = login(client)
    before = client.get("/api/config")
    assert before.status_code == 200
    assert before.json()["revision"] == 1
    response = client.put(
        "/api/config/risk",
        json={"risk_capital_inr": -1},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CONFIG"
    after = client.get("/api/config")
    assert after.json()["revision"] == 1


def test_valid_section_write_keeps_previous_revision(client):
    token = login(client)
    response = client.put(
        "/api/config/schedule",
        json={"analysis_cadence_seconds": 600, "holiday_calendar_source_id": None},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    previous = client.get("/api/config/revisions/1")
    assert previous.status_code == 200
    assert previous.json()["document"]["schedule"]["analysis_cadence_seconds"] == 300


def test_secret_text_is_redacted_in_audit(client):
    token = login(client)
    response = client.put(
        "/api/config/notify",
        json={"adapter": "log", "events": ["password=test-password"]},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200, response.text
    audit = client.get("/api/audit")
    assert "test-password" not in audit.text
    assert "[REDACTED]" in audit.text
