"""API for the multi-year research: history inventory, Groww fetch, daily research report.

Fetch and research run as one background job at a time (a fetch can take minutes; the
options PCR far longer). The job keeps a short log and its result in memory; the data
and report themselves are files under var/datasets/. Research only: nothing here
touches orders, the paper ledger or the live model.
"""

from __future__ import annotations

import math
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent
from app.errors import AppError
from app.research import multiyear_service as svc
from app.settings import Settings, get_settings

router = APIRouter()

EARLIEST = date(2020, 1, 1)
LOG_LINES = 200

_lock = threading.Lock()
_job: dict | None = None


def _spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="multiyear-research", daemon=True).start()


class FetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[Literal["NIFTY", "BANKNIFTY", "INDIAVIX", "SENSEX"]] = Field(min_length=1)
    intervals: list[Literal["1day", "15minute"]] = Field(min_length=1)
    start: date = EARLIEST
    end: date | None = None
    options: bool = False
    band_strikes: int = Field(default=5, ge=1, le=20)


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    with_pcr: bool = False
    initial_train: int = Field(default=500, ge=100, le=5000)
    step: int = Field(default=20, ge=5, le=250)


def _settings() -> Settings:
    return get_settings()


def get_db():
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _finite(value: Any) -> Any:
    """NaN / inf are not valid JSON; an undefined metric is reported as null."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_job() -> dict | None:
    with _lock:
        return None if _job is None else _finite({**_job, "log": list(_job["log"])})


def _start(kind: str, params: dict, work: Callable[[Callable[[str], None]], dict]) -> dict:
    global _job
    with _lock:
        if _job is not None and _job["status"] == "RUNNING":
            raise AppError("RESEARCH_JOB_RUNNING", f"A {_job['kind']} job is already running.", 409)
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "status": "RUNNING", "params": params,
               "started_at": _now(), "finished_at": None, "log": [], "result": None, "error": None}
        _job = job

    def log(line: str) -> None:
        with _lock:
            job["log"].append(line)
            del job["log"][:-LOG_LINES]

    def run() -> None:
        try:
            result = work(log)
            status, error = "SUCCEEDED", None
        except Exception as exc:  # reported to the operator, never swallowed
            result, status, error = None, "FAILED", f"{exc.__class__.__name__}: {exc}"[:500]
        with _lock:
            job.update(status=status, result=result, error=error, finished_at=_now())

    _spawn(run)
    return _public_job()


def _audit(session: Session, principal: dict, action: str, params: dict) -> None:
    session.add(AuditEvent(actor=principal.get("username", "operator"), action=action,
                           entity="research_multiyear", before=None, after=params))


@router.get("/api/research/multiyear")
def read_state(request: Request, settings: Settings = Depends(_settings)) -> dict:
    """Saved series, PCR, the latest report's summary and the current job."""
    read_session(request, settings)
    report = svc.load_report()
    return _finite({
        **svc.history_inventory(),
        "report": None if report is None else {
            "generated_at": report.get("generated_at"),
            "inputs": report.get("inputs"),
            "summary": report.get("summary"),
        },
        "job": _public_job(),
        "unavailable": ["MCX crude", "USD/INR", "FII/DII flows"],
    })


@router.get("/api/research/multiyear/report")
def read_report(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    report = svc.load_report()
    if report is None:
        raise AppError("RESEARCH_REPORT_MISSING", "No research report yet. Fetch history, then run the research.", 404)
    return _finite(report)


@router.post("/api/research/multiyear/fetch")
def start_fetch(
    body: FetchBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Start a Groww history download (read-only market data; no orders)."""
    principal = require_csrf(request, settings)
    end = body.end or datetime.now(svc.hl.IST).date()
    if body.start < EARLIEST:
        raise AppError("INVALID_RANGE", "Groww historical data starts in 2020.", 422)
    if body.start >= end:
        raise AppError("INVALID_RANGE", "Start must be before end.", 422)
    if body.options and ("NIFTY" not in body.symbols or "1day" not in body.intervals):
        if svc.hl.load_series("NSE-NIFTY", "1day") is None:
            raise AppError("PCR_NEEDS_NIFTY_DAILY", "The options PCR needs NIFTY 1day history; include it.", 422)
    params = {**body.model_dump(mode="json"), "end": end.isoformat()}

    def work(log: Callable[[str], None]) -> dict:
        from app.integrations.http import HttpxCaller
        from app.integrations.service import groww_read_token

        db = get_session_factory()()
        try:
            token = groww_read_token(db, settings)
        finally:
            db.close()
        start_dt = datetime.combine(body.start, datetime.min.time(), svc.hl.IST)
        end_dt = datetime.combine(end, datetime.min.time(), svc.hl.IST)
        log(f"Fetching {', '.join(body.symbols)} [{', '.join(body.intervals)}] {body.start} .. {end}")
        return svc.fetch_history(token=token, caller=HttpxCaller(), symbols=list(body.symbols),
                                 start=start_dt, end=end_dt, intervals=list(body.intervals),
                                 options=body.options, band_strikes=body.band_strikes, log=log)

    job = _start("fetch", params, work)
    _audit(session, principal, "research.multiyear.fetch", params)
    return {"job": job}


@router.post("/api/research/multiyear/run")
def start_research(
    body: ResearchBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Start the walk-forward daily / half-day research on the saved history."""
    principal = require_csrf(request, settings)
    params = body.model_dump(mode="json")

    def work(log: Callable[[str], None]) -> dict:
        log("Running walk-forward research")
        report, path = svc.run_daily_research(with_pcr=body.with_pcr, initial_train=body.initial_train, step=body.step)
        log(f"Report written to {path.name}")
        return {"summary": report["summary"], "generated_at": report.get("generated_at")}

    job = _start("research", params, work)
    _audit(session, principal, "research.multiyear.run", params)
    return {"job": job}
