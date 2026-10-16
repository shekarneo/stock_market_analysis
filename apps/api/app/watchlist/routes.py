"""Authenticated watchlist routes. No route here places or routes an order."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent, WatchlistSuggestion
from app.errors import AppError
from app.market.live_quotes import stored_observations
from app.settings import Settings, get_settings
from app.watchlist.service import accuracy, create_suggestion, evaluate_open, serialize

router = APIRouter()


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


class AddBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str = Field(min_length=1, max_length=32)
    contract: str = Field(min_length=1, max_length=64)
    option_type: str = Field(pattern="^(CE|PE)$")
    call: str | None = Field(default=None, max_length=80)
    entry_spot: float = Field(gt=0)
    target_points: float = Field(gt=0)
    stop_loss_points: float = Field(gt=0)
    model_premiums: dict = Field(default_factory=dict)
    data_class: str | None = Field(default=None, max_length=40)


def _listing(session: Session) -> dict:
    rows = session.scalars(select(WatchlistSuggestion).order_by(WatchlistSuggestion.created_at.desc())).all()
    return {"items": [serialize(r) for r in rows], "accuracy": accuracy(list(rows))}


@router.get("/api/watchlist")
def list_watchlist(request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    evaluate_open(session, stored_observations())
    return _listing(session)


@router.post("/api/watchlist")
def add_watchlist(
    body: AddBody, request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)
) -> dict:
    principal = require_csrf(request, settings)
    existing_open = session.scalar(
        select(WatchlistSuggestion).where(
            WatchlistSuggestion.contract == body.contract,
            WatchlistSuggestion.status == "OPEN",
        )
    )
    if existing_open is not None:
        return {"item": serialize(existing_open), "already_tracked": True}

    try:
        row = create_suggestion(
            session,
            instrument=body.instrument,
            contract=body.contract,
            option_type=body.option_type,
            call=body.call,
            entry_spot=body.entry_spot,
            target_points=body.target_points,
            stop_loss_points=body.stop_loss_points,
            model_premiums=body.model_premiums,
            data_class=body.data_class,
            created_by=principal.get("sub", "operator"),
        )
    except ValueError as exc:
        raise AppError("INVALID_SUGGESTION", str(exc), 422)
    session.add(AuditEvent(actor=principal.get("sub", "operator"), action="watchlist.add", entity=row.suggestion_id, before=None, after={"contract": row.contract}))
    return {"item": serialize(row)}


@router.post("/api/watchlist/evaluate")
def evaluate_watchlist(request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)) -> dict:
    require_csrf(request, settings)
    result = evaluate_open(session, stored_observations())
    return {**result, **_listing(session)}


@router.post("/api/watchlist/{suggestion_id}/cancel")
def cancel_watchlist(
    suggestion_id: str, request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)
) -> dict:
    require_csrf(request, settings)
    row = session.get(WatchlistSuggestion, suggestion_id)
    if row is None:
        raise AppError("NOT_FOUND", "Suggestion not found.", 404)
    if row.status == "OPEN":
        row.status = "CANCELLED"
        row.note = "Cancelled by operator; excluded from hit rate."
    return {"item": serialize(row)}


@router.post("/api/watchlist/clear")
def clear_watchlist(
    request: Request, session: Session = Depends(get_db), settings: Settings = Depends(_settings)
) -> dict:
    principal = require_csrf(request, settings)
    session.execute(delete(WatchlistSuggestion))
    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="watchlist.clear",
            entity="all",
            before=None,
            after=None,
        )
    )
    return {"cleared": True, **_listing(session)}

