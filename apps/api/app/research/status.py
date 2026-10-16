"""Read-only research desk status. It does not trade or invent missing inputs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config.store import current_config, ensure_seed
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.risk.ledger import read_kill_switch
from app.settings import Settings


def research_status(session: Session, settings: Settings) -> dict:
    ensure_seed(session, settings)
    config = current_config(session)
    switch = read_kill_switch(session)
    risk = config.risk
    blockers = []
    if risk.risk_capital_inr is None:
        blockers.append({"code": "MISSING_RISK_CAPITAL", "class": "operator"})
    if config.schedule.holiday_calendar_source_id is None:
        blockers.append({"code": "CALENDAR_NOT_CONFIGURED", "class": "external"})
    blockers.append({"code": "TICK_UNIT_UNVERIFIED", "class": "external"})
    blockers.append({"code": "CHARGES_UNVERIFIED", "class": "external"})
    blockers.append({"code": "RECONCILIATION_UNAVAILABLE", "class": "external"})
    blockers.append({"code": "MODEL_NOT_APPROVED", "class": "operator"})
    blockers.append({"code": "PAPER_TRADING_DISABLED", "class": "operator"})
    blockers.append({"code": "MARKET_DATA_UNVERIFIED", "class": "external"})
    return {
        "paper_trading_active": PAPER_TRADING_ACTIVE,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "live_trading_enabled": False,
        "configured_live_trading_enabled": config.runtime.live_trading_enabled,
        "unattended_orders": config.runtime.unattended_orders,
        "mode": config.runtime.mode.value,
        "kill_switch": None if switch is None else {"read": True, "enabled": switch},
        "risk_capital_inr": risk.risk_capital_inr,
        "holiday_calendar_source_id": config.schedule.holiday_calendar_source_id,
        "market_data": "unverified",
        "fills_persisted": False,
        "broker_called": False,
        "blockers": blockers,
    }
