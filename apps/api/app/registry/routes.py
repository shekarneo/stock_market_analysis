"""Registry HTTP routes. Writes use the session and CSRF token. Paper and live stay off."""

from __future__ import annotations

from app.registry.schema import FEATURE_SET

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.domain.tables import AuditEvent
from app.errors import AppError
from app.db import get_session_factory
from app.forecasting.store import ExperimentStoreError, experiment_store
from app.forecasting.walkforward import walkforward_store
from app.registry.service import (
    apply,
    compare_artifacts,
    list_models,
    model_detail,
    read_saved,
    register_artifact,
    register_definition,
    saved_experiments,
    select_for_research,
    transition,
)
from app.registry.store import RegistryError, registry_store
from app.settings import Settings, get_settings

router = APIRouter()

_STATUS = {
    "UNKNOWN_MODEL": 404,
    "NOT_FOUND": 404,
    "CHECKSUM_MISMATCH": 422,
    "MALFORMED_REGISTRY": 422,
    "IDEMPOTENCY_CONFLICT": 409,
    "REVISION_CONFLICT": 409,
    "MODEL_NOT_APPROVED": 403,
    "PAPER_APPROVAL_DISABLED": 403,
    "LIVE_APPROVAL_DISABLED": 403,
    "NOT_IMPLEMENTED": 501,
}


class DefineBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: str
    instrument: str
    horizon: str
    feature_schema_version: str = FEATURE_SET
    target_version: str = "binary-1"
    recorded_at: str | None = None
    expected_revision: int | None = None


class RegisterBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    experiment_id: str
    expected_revision: int | None = None


class TransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str
    reason: str
    confirm: bool
    experiment_ids: list[str] = Field(default_factory=list)
    recorded_at: str | None = None
    acknowledge_not_market_evidence: bool = False
    claim_market_performance: bool = False
    real_market_data_verified: bool = False
    expected_revision: int | None = None


class ResearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    version: str
    instrument: str
    horizon: str
    reason: str
    confirm: bool
    recorded_at: str | None = None
    expected_revision: int | None = None


class PaperBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = ""
    version: str = ""
    instrument: str = ""
    horizon: str = ""
    reason: str = ""


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


def _fail(exc: Exception) -> None:
    if isinstance(exc, RegistryError):
        raise AppError(exc.code, exc.message, _STATUS.get(exc.code, 422)) from exc
    if isinstance(exc, ExperimentStoreError):
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc
    raise exc


def _audit(session: Session, actor: str, action: str, entity: str, after: dict) -> None:
    session.add(AuditEvent(actor=actor, action=action, entity=entity, before=None, after=after))


@router.get("/api/models")
def get_models(
    request: Request,
    underlying: str | None = None,
    horizon: str | None = None,
    settings: Settings = Depends(_settings),
) -> dict:
    read_session(request, settings)
    return list_models(registry_store().read(), instrument=underlying, horizon=horizon)


@router.get("/api/models/compare")
def get_model_compare(
    request: Request,
    items: str,
    settings: Settings = Depends(_settings),
) -> dict:
    read_session(request, settings)
    parsed = []
    for raw in items.split(","):
        kind, experiment_id, family = (raw.split(":") + ["", ""])[:3]
        if kind not in {"m3", "m4"} or not experiment_id or not family:
            raise AppError("NOT_COMPARABLE", "Each item is kind:experiment_id:family.", 422)
        try:
            artifact = experiment_store().read(experiment_id) if kind == "m3" else walkforward_store().read(experiment_id)
        except ExperimentStoreError as exc:
            _fail(exc)
        parsed.append({"kind": kind, "artifact": artifact, "family": family})
    try:
        return compare_artifacts(parsed)
    except RegistryError as exc:
        _fail(exc)


@router.get("/api/models/activations")
def get_activations(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    document = registry_store().read()
    return {
        "research_selections": document["research_selections"],
        "paper_slot": None,
        "live_slot": None,
        "paper_activations": [],
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


@router.get("/api/experiments")
def get_experiments(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    return saved_experiments(experiment_store(), walkforward_store())


@router.get("/api/experiments/{kind}/{experiment_id}")
def get_experiment(
    kind: str,
    experiment_id: str,
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    read_session(request, settings)
    try:
        return read_saved(kind, experiment_id, experiment_store(), walkforward_store())
    except (RegistryError, ExperimentStoreError) as exc:
        _fail(exc)


@router.get("/api/forecasts")
def get_forecasts(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    live_param = request.query_params.get("live", "").lower()
    if live_param in {"true", "1", "yes"} or request.headers.get("x-live-forecasts") == "1":
        from app.forecasting.live_forecast import generate_all_live_forecasts
        return generate_all_live_forecasts()
    return {
        "forecasts": [],
        "forecast_ready": False,
        "note": "NOT_AVAILABLE. This milestone does not emit live or synthetic forecasts.",
    }


@router.post("/api/models")
def post_model(
    body: DefineBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    actor = require_csrf(request, settings)["sub"]
    try:
        result = apply(
            registry_store(),
            lambda document: register_definition(
                document,
                family=body.family,
                instrument=body.instrument,
                horizon=body.horizon,
                feature_schema_version=body.feature_schema_version,
                target_version=body.target_version,
                actor=actor,
                recorded_at=body.recorded_at,
                expected_revision=body.expected_revision,
            ),
            idempotency_key=request.headers.get("idempotency-key"),
            body=body.model_dump(mode="json"),
        )
    except RegistryError as exc:
        _fail(exc)
    _audit(session, actor, "model.register", result["version"]["version_id"], {"status": result["version"]["status"]})
    return JSONResponse(status_code=200, content=result)


@router.post("/api/models/registrations")
def post_registration(
    body: RegisterBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    actor = require_csrf(request, settings)["sub"]
    try:
        artifact = (
            experiment_store().read(body.experiment_id) if body.kind == "m3" else walkforward_store().read(body.experiment_id)
        )
        result = apply(
            registry_store(),
            lambda document: register_artifact(
                document,
                artifact,
                kind=body.kind,
                actor=actor,
                expected_revision=body.expected_revision,
            ),
            idempotency_key=request.headers.get("idempotency-key"),
            body=body.model_dump(mode="json"),
        )
    except (RegistryError, ExperimentStoreError) as exc:
        _fail(exc)
    _audit(session, actor, "model.register", body.experiment_id, {"kind": body.kind, "duplicate": result["duplicate"]})
    return JSONResponse(status_code=200, content=result)


@router.post("/api/models/research-selection")
def post_research_selection(
    body: ResearchBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    actor = require_csrf(request, settings)["sub"]
    try:
        result = apply(
            registry_store(),
            lambda document: select_for_research(
                document,
                model_id=body.model_id,
                version=body.version,
                instrument=body.instrument,
                horizon=body.horizon,
                reason=body.reason,
                confirm=body.confirm,
                actor=actor,
                recorded_at=body.recorded_at,
                expected_revision=body.expected_revision,
            ),
            idempotency_key=request.headers.get("idempotency-key"),
            body=body.model_dump(mode="json"),
        )
    except RegistryError as exc:
        _fail(exc)
    _audit(session, actor, "model.research_select", result["selection"]["version_id"], {"reason": body.reason})
    return JSONResponse(status_code=200, content=result)


@router.post("/api/models/paper-activation")
def post_paper_activation(
    body: PaperBody,
    request: Request,
    settings: Settings = Depends(_settings),
) -> None:
    require_csrf(request, settings)
    raise AppError("MODEL_NOT_APPROVED", "Paper activation is not implemented. No paper slot was changed.", 403)


@router.post("/api/models/paper-rollback")
def post_paper_rollback(
    body: PaperBody,
    request: Request,
    settings: Settings = Depends(_settings),
) -> None:
    require_csrf(request, settings)
    raise AppError("MODEL_NOT_APPROVED", "Paper rollback is not implemented. No paper slot was changed.", 403)


@router.post("/api/models/{model_id}/versions/{version}/transitions")
def post_transition(
    model_id: str,
    version: str,
    body: TransitionBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    actor = require_csrf(request, settings)["sub"]
    try:
        result = apply(
            registry_store(),
            lambda document: transition(
                document,
                model_id=model_id,
                version=version,
                to_status=body.to,
                reason=body.reason,
                confirm=body.confirm,
                actor=actor,
                experiment_ids=body.experiment_ids,
                recorded_at=body.recorded_at,
                acknowledge_not_market_evidence=body.acknowledge_not_market_evidence,
                claim_market_performance=body.claim_market_performance,
                real_market_data_verified=body.real_market_data_verified,
                expected_revision=body.expected_revision,
            ),
            idempotency_key=request.headers.get("idempotency-key"),
            body={"model_id": model_id, "version": version, **body.model_dump(mode="json")},
        )
    except RegistryError as exc:
        _fail(exc)
    action = "model.approve" if body.to == "APPROVED_FOR_RESEARCH" else "model.transition"
    if body.to == "DISABLED":
        action = "model.disable"
    _audit(session, actor, action, result["version"]["version_id"], {"to": body.to, "reason": body.reason})
    return JSONResponse(status_code=200, content=result)


@router.post("/api/models/{model_id}/versions/{version}/evaluate")
def post_evaluate(
    model_id: str,
    version: str,
    request: Request,
    settings: Settings = Depends(_settings),
) -> None:
    require_csrf(request, settings)
    raise AppError("NOT_IMPLEMENTED", "Evaluation jobs are not started from this route. Register an existing M4 artifact instead.", 501)


@router.get("/api/models/{model_id}/versions/{version}")
def get_version(
    model_id: str,
    version: str,
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    read_session(request, settings)
    try:
        detail = model_detail(registry_store().read(), model_id)
    except RegistryError as exc:
        _fail(exc)
    row = next((item for item in detail["versions"] if item["version"] == version), None)
    if row is None:
        raise AppError("UNKNOWN_MODEL", "That model version is not registered.", 404)
    if row["evaluation_report_id"] is None:
        row["evaluation_status"] = "NOT_EVALUATED"
    return row


@router.get("/api/models/{model_id}")
def get_model(model_id: str, request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    try:
        return model_detail(registry_store().read(), model_id)
    except RegistryError as exc:
        _fail(exc)
