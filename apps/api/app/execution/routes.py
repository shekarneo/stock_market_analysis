"""Explicit paper-simulation route. It does not call a broker."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
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
    tick_size: str | None = None
    charges_per_lot: str | None = None
    expected_net: str | None = None
    dataset: dict | None = None
    forecast: dict | None = None
    quote: dict | None = None
    master: dict | None = None
    entry_plan: EntryPlanBody | None = None
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
    status = 200 if result["code"] == "VETOED" else 422
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
