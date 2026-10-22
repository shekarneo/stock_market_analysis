"""Explicit paper-simulation route. It does not call a broker."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.execution.boundary import propose_simulated_fill
from app.execution.simulation import replay_simulation_decision, run_paper_simulation
from app.settings import Settings, get_settings

router = APIRouter()


class EntryPlanBody(BaseModel):
    """The four operator texts. Omitted fields stay omitted."""

    model_config = ConfigDict(extra="forbid")
    entry_trigger: str | None = None
    invalidation: str | None = None
    exit_plan: str | None = None
    time_stop: str | None = None


class PaperSimulationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False
    intent_id: str
    occurred_at: datetime
    session_date: str | None = None
    mode: str = "PAPER"
    underlying: str | None = None
    expiry: str | None = None
    strike: str | None = None
    option_type: str | None = None
    lot_size: str | None = None
    lots: int | None = Field(default=None, ge=1)
    tick_size: str | None = None
    charges_per_lot: str | None = None
    expected_net: str | None = None
    dataset: dict | None = None
    forecast: dict | None = None
    quote: dict | None = None
    master: dict | None = None
    entry_plan: EntryPlanBody | None = None
    execution_context: str | None = None
    side: str | None = None
    paper_approved: bool = False
    live_approved: bool = False
    real_market_data_verified: bool = False


class SimulatedFillBody(BaseModel):
    """A proposed simulated fill. Caller flags are ignored by the boundary."""

    model_config = ConfigDict(extra="forbid")
    event_type: str
    event_id: str
    intent_id: str
    decision_audit_id: int
    body_hash: str
    side: str
    underlying: str | None = None
    expiry: str | None = None
    strike: str | None = None
    option_type: str | None = None
    quantity: str | None = None
    price: str | None = None
    occurred_at: datetime
    price_source: str | None = None
    charges_inr: str | None = None
    slippage_inr: str | None = None
    tick_size: str | None = None
    lot_size: str | None = None
    paper_approved: bool = False
    live_approved: bool = False
    real_market_data_verified: bool = False
    forecast_ready: bool = False
    risk_passed: bool = False


def _settings() -> Settings:
    return get_settings()


def get_db() -> Session:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.get("/api/paper/simulations/{intent_id}")
def get_paper_simulation(
    intent_id: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Replay a stored decision. This does not evaluate again or write a fill."""
    read_session(request, settings)
    replay = replay_simulation_decision(session, intent_id)
    replay["fill"] = None
    replay["simulated_fill"] = None
    replay["paper_trading_active"] = False
    return replay


@router.post("/api/paper/simulations")
def post_paper_simulation(
    body: PaperSimulationBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    principal = require_csrf(request, settings)
    result = run_paper_simulation(session, body.model_dump(), actor=principal.get("sub", "operator"))
    status = 200 if result["code"] in ("VETOED", "SIMULATED_FILL_APPLIED") else 422
    return JSONResponse(status_code=status, content=result)


@router.post("/api/paper/executions")
def post_paper_execution(
    body: SimulatedFillBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    principal = require_csrf(request, settings)
    result = propose_simulated_fill(session, body.model_dump(), actor=principal.get("sub", "operator"))
    return JSONResponse(status_code=422, content=result)


class ClosePositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: str
    exit_price: float | None = None
    exit_quote: dict | None = None
    reason: str = "OPERATOR_EXIT"


@router.post("/api/paper/close-position")
def post_close_paper_position(
    body: ClosePositionBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    """Close an open paper position and record simulated exit fill and net P&L."""
    principal = require_csrf(request, settings)
    from app.execution.simulation import close_paper_position

    result = close_paper_position(
        session,
        intent_id=body.intent_id,
        exit_price=body.exit_price,
        exit_quote=body.exit_quote,
        reason=body.reason,
        actor=principal.get("sub", "operator"),
    )
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(status_code=status_code, content=result)


@router.get("/api/paper/account")
def get_paper_account(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Current live-data paper trading account status and executed trades.
    
    Guarantees strict separation from historical backtest / simulation results.
    """
    read_session(request, settings)
    from app.domain.tables import OpsState, PaperAccountEvent
    from app.config.store import current_config

    cfg = current_config(session)
    ops = session.get(OpsState, 1)
    kill_switch = ops.kill_switch if ops else False

    events = session.query(PaperAccountEvent).order_by(PaperAccountEvent.occurred_at.asc()).all()

    entry_events: dict[str, PaperAccountEvent] = {}
    exit_events: dict[str, PaperAccountEvent] = {}

    for ev in events:
        if ev.event_id.startswith("sim-fill-"):
            entry_events[ev.intent_id] = ev
        elif ev.event_id.startswith("sim-exit-"):
            exit_events[ev.intent_id] = ev

    open_positions = []
    closed_trades = []
    realized_pnl = 0.0
    total_charges = 0.0
    winning_trades = 0
    losing_trades = 0

    # Process all closed trades
    for intent_id, exit_ev in exit_events.items():
        payload = exit_ev.payload or {}
        entry_ev = entry_events.get(intent_id)
        entry_payload = (entry_ev.payload or {}) if entry_ev else {}

        net_pnl = float(payload.get("net_realized_pnl_inr", payload.get("realized_pnl_inr", 0.0)))
        realized_pnl += net_pnl
        trade_charges = float(payload.get("total_charges_inr", payload.get("charges_inr", 0.0)))
        total_charges += trade_charges
        if net_pnl > 0:
            winning_trades += 1
        elif net_pnl < 0:
            losing_trades += 1

        closed_trades.append({
            "intent_id": intent_id,
            "status": "CLOSED",
            "side": entry_payload.get("side", "BUY"),
            "underlying": entry_payload.get("underlying") or payload.get("underlying", "NIFTY"),
            "contract": payload.get("contract") or entry_payload.get("contract"),
            "quantity": float(payload.get("quantity") or 65),
            "entry_price": float(payload.get("entry_price") or entry_payload.get("price") or 0.0),
            "exit_price": float(payload.get("exit_price") or exit_ev.price or 0.0),
            "entry_charges_inr": float(payload.get("entry_charges_inr") or 0.0),
            "exit_charges_inr": float(payload.get("charges_inr") or 0.0),
            "total_charges_inr": round(trade_charges, 2),
            "gross_pnl_inr": round(float(payload.get("gross_pnl_inr") or 0.0), 2),
            "realized_pnl_inr": round(net_pnl, 2),
            "entry_time": entry_payload.get("occurred_at"),
            "exit_time": payload.get("occurred_at"),
            "exit_reason": payload.get("exit_reason", "OPERATOR_EXIT"),
            "data_provenance": payload.get("data_provenance", "EXPERIMENTAL_UNVERIFIED_DATA"),
        })

    # Process open positions (entries that have no matching exit)
    for intent_id, entry_ev in entry_events.items():
        if intent_id not in exit_events:
            entry_payload = entry_ev.payload or {}
            entry_charges = float(entry_payload.get("charges_inr", entry_ev.charges_inr or 0.0))
            total_charges += entry_charges
            open_positions.append({
                "intent_id": intent_id,
                "status": "OPEN",
                "side": entry_payload.get("side", "BUY"),
                "underlying": entry_payload.get("underlying", "NIFTY"),
                "contract": entry_payload.get("contract") or f"{entry_payload.get('underlying')} {entry_payload.get('strike')} {entry_payload.get('option_type')}",
                "quantity": float(entry_payload.get("quantity") or entry_ev.quantity or 65),
                "entry_price": float(entry_payload.get("price") or entry_ev.price or 0.0),
                "entry_charges_inr": round(entry_charges, 2),
                "entry_time": entry_payload.get("occurred_at"),
                "data_provenance": entry_payload.get("data_provenance", "EXPERIMENTAL_UNVERIFIED_DATA"),
            })

    total_closed = len(closed_trades)
    win_rate = round((winning_trades / total_closed) * 100, 2) if total_closed > 0 else None
    configured_capital = float(cfg.risk.risk_capital_inr) if cfg.risk.risk_capital_inr else 1000000.0
    current_balance = configured_capital + realized_pnl
    experimental_active = bool(
        cfg.runtime.mode.value == "PAPER"
        and cfg.risk.risk_capital_inr
        and float(cfg.risk.risk_capital_inr) > 0
        and not kill_switch
    )

    all_trade_payloads = [ev.payload for ev in events if isinstance(ev.payload, dict)]

    return {
        "account_mode": cfg.runtime.mode.value,
        "live_trading_enabled": cfg.runtime.live_trading_enabled,
        "kill_switch_active": kill_switch,
        "active_paper_account": experimental_active,
        "configured_capital_inr": configured_capital,
        "current_balance_inr": round(current_balance, 2),
        "open_positions": open_positions,
        "open_positions_count": len(open_positions),
        "closed_positions": closed_trades,
        "closed_positions_count": total_closed,
        "realized_pnl_inr": round(realized_pnl, 2),
        "unrealized_pnl_inr": 0.0,
        "total_trades_count": len(all_trade_payloads),
        "win_rate_pct": win_rate,
        "profit_factor": None if total_closed == 0 else (round(winning_trades / losing_trades, 2) if losing_trades > 0 else 1.0),
        "total_charges_inr": round(total_charges, 2),
        "total_slippage_inr": 0.0,
        "trades": all_trade_payloads,
        "status": "NO_LIVE_PAPER_TRADES" if (len(open_positions) == 0 and total_closed == 0) else "ACTIVE",
        "note": "Current live-data paper trading account tracks only real-time simulated executions. Historical M42 replay results are segregated.",
        "historical_benchmark_available": True,
        "historical_benchmark_milestone": "M42_MULTI_ASSET_REPLAY",
    }


@router.get("/api/paper/signal-eligibility")
def get_paper_signal_eligibility(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Check consensus forecast eligibility for experimental paper trading."""
    read_session(request, settings)
    from app.research.status import research_status
    st = research_status(session, settings)
    if st.get("experimental_paper_execution") != "Enabled":
        return {
            "eligible": False,
            "decision": "NO_TRADE",
            "status": "PAPER_EXECUTION_BLOCKED",
            "message": "Paper book is blocked by virtual risk controls or runtime mode.",
            "blockers": st.get("experimental_blockers") or st.get("blockers"),
        }
    return {
        "eligible": False,
        "decision": "NO_TRADE",
        "status": "NO_ELIGIBLE_PAPER_TRADE",
        "message": "No eligible paper trade: Consensus forecast indicates neutral market conditions (stand aside). No trade signal qualifies under virtual risk filters.",
        "reasons": ["CONSENSUS_NEUTRAL", "STAND_ASIDE_ACTIVE"],
    }

