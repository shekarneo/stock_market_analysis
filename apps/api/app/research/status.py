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
    mode = config.runtime.mode.value

    # 1. Evaluate Virtual Risk Controls for Experimental Paper Trading
    has_capital = risk.risk_capital_inr is not None and float(risk.risk_capital_inr) > 0
    has_pos_limit = risk.max_open_positions is not None and risk.max_open_positions > 0
    has_risk_fraction = risk.max_risk_fraction_per_trade is not None and risk.max_risk_fraction_per_trade > 0
    has_daily_loss = risk.daily_loss_fraction is not None and risk.daily_loss_fraction > 0
    from app.risk.external_halt import external_halt_status

    external_halt = external_halt_status()
    kill_switch_active = bool(switch) or external_halt["halted"]

    virtual_risk_configured = has_capital and has_pos_limit and has_risk_fraction and has_daily_loss
    experimental_paper_enabled = (mode == "PAPER") and (not kill_switch_active) and virtual_risk_configured

    # Check simulated fills count in PaperAccountEvent
    from app.domain.tables import PaperAccountEvent
    try:
        fill_count = session.query(PaperAccountEvent).filter(
            PaperAccountEvent.event_type.in_(("FILL", "PARTIAL_FILL"))
        ).count()
    except Exception:
        fill_count = 0

    blockers = []
    experimental_blockers = []

    if not has_capital:
        blockers.append({"code": "MISSING_RISK_CAPITAL", "class": "operator"})
        experimental_blockers.append({"code": "MISSING_RISK_CAPITAL", "class": "operator"})
    if not has_pos_limit:
        experimental_blockers.append({"code": "MISSING_POSITION_LIMIT", "class": "risk"})
    if not has_risk_fraction:
        experimental_blockers.append({"code": "MISSING_TRADE_RISK_LIMIT", "class": "risk"})
    if not has_daily_loss:
        experimental_blockers.append({"code": "MISSING_DAILY_LOSS_LIMIT", "class": "risk"})
    if kill_switch_active:
        blockers.append({"code": "KILL_SWITCH_ACTIVE", "class": "risk"})
        experimental_blockers.append({"code": "KILL_SWITCH_ACTIVE", "class": "risk"})
    if external_halt["halted"]:
        blockers.append({"code": "EXTERNAL_HALT", "class": "risk"})
        experimental_blockers.append({"code": "EXTERNAL_HALT", "class": "risk"})
    if mode != "PAPER":
        experimental_blockers.append({"code": "MODE_NOT_PAPER", "class": "operator"})

    if config.schedule.holiday_calendar_source_id is None:
        blockers.append({"code": "CALENDAR_NOT_CONFIGURED", "class": "external"})

    # When experimental paper execution is disabled, maintain legacy blockers for compatibility
    if not experimental_paper_enabled:
        blockers.append({"code": "TICK_UNIT_UNVERIFIED", "class": "external"})
        blockers.append({"code": "CHARGES_UNVERIFIED", "class": "external"})
        blockers.append({"code": "RECONCILIATION_UNAVAILABLE", "class": "external"})
        blockers.append({"code": "MODEL_NOT_APPROVED", "class": "operator"})
        blockers.append({"code": "PAPER_TRADING_DISABLED", "class": "operator"})
        blockers.append({"code": "MARKET_DATA_UNVERIFIED", "class": "external"})

    return {
        "external_halt": external_halt,

        # State 1: Operational Mode
        "mode": mode,
        "operational_mode": mode,

        # State 2: Forecast Generation & Evaluation
        "forecast_evaluation_status": "Active",
        "forecast_ready": False,  # Safety flag stays False for production live approval

        # State 3: Experimental Paper Execution
        "experimental_paper_execution": "Enabled" if experimental_paper_enabled else "Blocked",
        "experimental_paper_active": experimental_paper_enabled,
        "paper_trading_active": experimental_paper_enabled,  # Maps directly to dashboard tile

        # State 4: Approved Production Paper Execution
        "approved_paper_execution": "Locked" if not config.runtime.live_trading_enabled else "Approved",
        "paper_approved": False,

        # State 5: Live Broker Execution
        "live_broker_execution": "Locked",
        "live_trading_enabled": False,
        "live_approved": False,

        # Data Verification
        "data_verification": "Unverified",
        "real_market_data_verified": False,
        "market_data": "unverified",

        # Config & Fills
        "configured_live_trading_enabled": config.runtime.live_trading_enabled,
        "unattended_orders": config.runtime.unattended_orders,
        "kill_switch": None if switch is None else {"read": True, "enabled": switch},
        "risk_capital_inr": risk.risk_capital_inr,
        "holiday_calendar_source_id": config.schedule.holiday_calendar_source_id,
        "fills_persisted": fill_count > 0,
        "fills_count": fill_count,
        "broker_called": False,
        "blockers": blockers,
        "experimental_blockers": experimental_blockers,
    }
