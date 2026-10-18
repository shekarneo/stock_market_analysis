from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.settings import REPO_ROOT

from app.analysis.routes import router as analysis_router
from app.account import account_status, authenticate, change_password, create_account, profile, update_profile
from app.auth import logout, read_session, require_csrf, start_session
from app.config.schemas import DataSource, OperatingMode
from app.config.store import current_config, ensure_seed, latest, replace_section, upsert_source
from app.db import get_engine, get_session_factory, reset_engine
from app.domain.tables import AuditEvent, ConfigRevision, OpsState
from app.errors import AppError
from app.instruments import TRADABLE_UNDERLYINGS, underlying_list_text
from app.execution.orders import request_order
from app.execution.routes import router as paper_router
from app.features.pipeline import DatasetBuildResult
from app.features.service import build_from_provider, feature_store
from app.features.store import DatasetStoreError, compare_manifests
from app.forecasting.store import ExperimentStoreError, experiment_store
from app.forecasting.walkforward import WalkForwardConfig, run_from_provider, walkforward_store
from app.registry.service import list_models, saved_experiments
from app.registry.store import registry_store
from app.logging_config import configure_logging
from app.integrations.routes import router as integrations_router
from app.market.history_routes import router as history_router
from app.registry.routes import router as registry_router
from app.options.candidate import assess_option_candidate
from app.options.proposal import build_research_proposal
from app.research.decision import build_research_decision
from app.research.status import research_status
from app.risk.ledger import EVENT_TYPES
from app.risk.projection import project_journal
from app.market.schemas import IST
from app.market.service import assert_provider_name, build_history, build_snapshot
from app.news.fetch import fetch_news_source, unavailable_reader
from app.news.routes import router as news_router
from app.settings import Settings, get_settings
from app.watchlist.routes import router as watchlist_router

log = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    try:
        session = get_session_factory()()
        try:
            ensure_seed(session, settings)
            from app.integrations.service import ensure_env_credentials_loaded
            ensure_env_credentials_loaded(session, settings)
            session.commit()
        finally:
            session.close()
    except Exception:
        log.exception("database unavailable at startup")
    import os
    if not os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("TESTING"):
        from app.market.poller import start_market_poller, stop_market_poller
        start_market_poller(settings)
        try:
            yield
        finally:
            stop_market_poller()
    else:
        yield



app = FastAPI(title="India Market Master", version="0.1.0", lifespan=lifespan)
app.include_router(analysis_router)
app.include_router(news_router)
app.include_router(registry_router)
app.include_router(history_router)
app.include_router(integrations_router)
app.include_router(paper_router)
app.include_router(watchlist_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["content-type", "x-csrf-token"],
)


@app.exception_handler(AppError)
def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str
    username: str | None = None


class SignupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    display_name: str = ""


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = None
    timezone: str | None = None


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str
    new_password: str


class LiveOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""


class FeatureDatasetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    provider: str = "synthetic"
    as_of: datetime | None = None


class WalkForwardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    provider: str = "synthetic"
    initial_train_size: int = 9
    validation_size: int = 5
    test_size: int = 4
    step_size: int = 4
    min_train: int = 8
    min_validation: int = 4
    min_test: int = 4


def settings_dep() -> Settings:
    return get_settings()


@app.get("/health")
def health(settings: Settings = Depends(settings_dep)) -> dict:
    database = False
    mode = None
    live_trading_enabled = None
    kill_switch = None
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        session = get_session_factory()()
        try:
            ensure_seed(session, settings)
            config = current_config(session)
            ops = session.get(OpsState, 1)
            session.commit()
            database = True
            mode = config.runtime.mode.value
            live_trading_enabled = config.runtime.live_trading_enabled
            kill_switch = None if ops is None else bool(ops.kill_switch)
        finally:
            session.close()
    except Exception:
        log.exception("health database check failed")
        database = False
    return {
        "status": "ok" if database else "degraded",
        "process": True,
        "database": database,
        "mode": mode,
        "live_trading_enabled": live_trading_enabled,
        "live_order_server_flag": settings.live_order_server_flag,
        "kill_switch": kill_switch,
    }


@app.post("/api/session/login")
def session_login(
    body: LoginBody,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    actor = authenticate(session, password=body.password, env_password=settings.operator_password, username=body.username)
    start_session(response, settings, username=actor["username"])
    session.add(AuditEvent(actor=actor["username"], action="session.login", entity=actor["source"], before=None, after=None))
    return {"actor": "operator", "username": actor["username"], "display_name": actor["display_name"], "source": actor["source"]}


@app.post("/api/session/logout")
def session_logout(response: Response) -> dict:
    logout(response)
    return {"actor": None}


@app.get("/api/session")
def session_status(request: Request, session: Session = Depends(get_db), settings: Settings = Depends(settings_dep)) -> dict:
    payload = read_session(request, settings)
    return {"actor": "operator", "username": payload.get("username", "operator"), **profile(session)}


@app.get("/api/account/status")
def read_account_status(session: Session = Depends(get_db)) -> dict:
    """Whether a stored operator account exists. This is readable before sign-in so signup can show."""
    return account_status(session)


@app.post("/api/account/signup")
def account_signup(
    body: SignupBody,
    response: Response,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    row = create_account(session, username=body.username, password=body.password, display_name=body.display_name)
    start_session(response, settings, username=row.username)
    session.add(AuditEvent(actor=row.username, action="account.created", entity="operator_accounts", before=None, after=None))
    response.status_code = 201
    return {"actor": "operator", "username": row.username, "display_name": row.display_name, "source": "database"}


@app.get("/api/account/profile")
def read_profile(request: Request, session: Session = Depends(get_db), settings: Settings = Depends(settings_dep)) -> dict:
    read_session(request, settings)
    return profile(session)


@app.put("/api/account/profile")
def write_profile(
    body: ProfileBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    principal = require_csrf(request, settings)
    before = profile(session)
    after = update_profile(session, display_name=body.display_name, timezone_name=body.timezone)
    session.add(AuditEvent(actor=principal.get("username", "operator"), action="account.profile", entity="operator_accounts", before=before, after=after))
    return after


@app.post("/api/account/password")
def write_password(
    body: PasswordBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    principal = require_csrf(request, settings)
    change_password(session, current=body.current_password, new=body.new_password)
    session.add(AuditEvent(actor=principal.get("username", "operator"), action="account.password", entity="operator_accounts", before=None, after=None))
    return {"changed": True}


@app.get("/api/options/research")
def read_options_research(request: Request, settings: Settings = Depends(settings_dep)) -> dict:
    """A research proposal with no contract. Premiums and expected net stay null."""
    read_session(request, settings)
    proposal = build_research_proposal(None, None)
    proposal["live_trading_enabled"] = False
    proposal["order_connected"] = False
    return proposal


@app.get("/api/accounting/status")
def read_accounting_status(request: Request, settings: Settings = Depends(settings_dep)) -> dict:
    """The enforced book. This route does not post a fill or read a broker."""
    read_session(request, settings)
    return {
        "event_types": sorted(EVENT_TYPES),
        "fill_accepted": False,
        "fills_persisted": False,
        "paper_cash_rule": "equals_configured_capital_when_capital_is_set_otherwise_null",
        "open_premium_rule": "must_remain_zero",
        "position_count_rule": "must_remain_zero",
        "partial_release": "PARTIAL_RELEASE_UNDEFINED",
        "reservation_release_status": "RULE_UNDEFINED",
        "missing_charge": "unknown_not_zero",
        "reconciliation_tolerance": None,
        "broker_snapshot": None,
        "paper_trading_active": False,
        "live_trading_enabled": False,
        "broker_called": False,
    }


@app.get("/api/accounting/projection")
def read_accounting_projection(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Replay the journal. This route does not post an event or read a broker."""
    read_session(request, settings)
    projected = project_journal(session)
    projected["reservation_release_status"] = "RULE_UNDEFINED"
    projected["reservation_release_inr"] = None
    return projected


class OptionCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provenance: str
    underlying: str | None = None
    exchange: str | None = None
    segment: str | None = None
    expiry: str | None = None
    strike: float | None = None
    option_type: str | None = None
    trading_symbol: str | None = None
    instrument_id: str | None = None
    lot_size: float | None = None
    tick_size: float | None = None
    bid: float | None = None
    ask: float | None = None
    premium: float | None = None
    quote_timestamp: str | None = None


def _local_decision(session: Session, settings: Settings, underlying: str | None) -> dict:
    if underlying is not None and underlying not in TRADABLE_UNDERLYINGS:
        raise AppError("INVALID_UNDERLYING", f"Underlying must be {underlying_list_text(TRADABLE_UNDERLYINGS)}.", 400)
    status = research_status(session, settings)
    ensure_seed(session, settings)
    snapshot = build_snapshot(current_config(session), now=datetime.now(IST), provider_name="synthetic")
    listed = list_models(registry_store().read(), instrument=None, horizon=None)
    experiments = saved_experiments(experiment_store(), walkforward_store())
    return build_research_decision(
        underlying=underlying,
        snapshot=snapshot,
        models=listed,
        experiments=experiments,
        blockers=status["blockers"],
    )


@app.get("/api/research/decision")
def read_research_decision(
    request: Request,
    underlying: str | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Join the local snapshot, model lineage, and an empty options proposal."""
    read_session(request, settings)
    return _local_decision(session, settings, underlying)


@app.post("/api/options/candidates")
def read_option_candidate(
    body: OptionCandidateBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    """Assess one local fixture. This does not list the contract or place an order."""
    require_csrf(request, settings)
    decision = _local_decision(session, settings, body.underlying if body.underlying in TRADABLE_UNDERLYINGS else None)
    assessed = assess_option_candidate(body.model_dump(), decision=decision, as_of=datetime.now(IST))
    status = 200 if assessed["ok"] else 422
    return JSONResponse(status_code=status, content=assessed)


@app.get("/api/research/status")
def read_research_status(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    return research_status(session, settings)


@app.get("/api/config")
def read_config(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    ensure_seed(session, settings)
    row = latest(session)
    return {"revision": row.revision, "document": row.document}


@app.get("/api/config/revisions/{revision}")
def read_revision(
    revision: int,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    row = session.get(ConfigRevision, revision)
    if row is None:
        raise AppError("NOT_FOUND", "Config revision not found.", 404)
    return {"revision": row.revision, "document": row.document, "actor": row.actor}


@app.put("/api/config/{section}")
async def write_section(
    section: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    require_csrf(request, settings)
    ensure_seed(session, settings)
    body = await request.json()
    if not isinstance(body, dict):
        raise AppError("INVALID_CONFIG", "Config section must be a JSON object.", 422)
    confirm_live = body.get("confirm_live")
    payload = {key: value for key, value in body.items() if key != "confirm_live"}
    row = replace_section(session, settings, section, payload, "operator", confirm_live)
    return {"revision": row.revision, "document": row.document}


@app.post("/api/config/sources")
def create_source(
    source: DataSource,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    require_csrf(request, settings)
    ensure_seed(session, settings)
    row = upsert_source(session, settings, source, "operator")
    return {"revision": row.revision, "document": row.document}


@app.post("/api/config/sources/{source_id}/test")
def test_source(
    source_id: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    require_csrf(request, settings)
    ensure_seed(session, settings)
    config = current_config(session)
    source = next((item for item in config.sources if item.id == source_id), None)
    if source is None:
        raise AppError("NOT_FOUND", "Source not found.", 404)
    fetch_news_source(source, unavailable_reader)
    return {"fetched": False}


@app.get("/api/market/snapshot")
def market_snapshot(
    request: Request,
    provider: str = "synthetic",
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    read_session(request, settings)
    ensure_seed(session, settings)
    try:
        assert_provider_name(provider)
    except ValueError as exc:
        raise AppError("INVALID_PROVIDER", str(exc), 400) from exc
    payload = build_snapshot(current_config(session), now=datetime.now(IST), provider_name=provider)
    status = 200 if payload["ok"] else 422
    if payload["failures"] and payload["failures"][0]["code"] == "GROWW_NOT_VERIFIED":
        status = 501
    return JSONResponse(status_code=status, content=payload)


@app.get("/api/market/history")
def market_history(
    instrument: str,
    request: Request,
    provider: str = "synthetic",
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    read_session(request, settings)
    ensure_seed(session, settings)
    try:
        assert_provider_name(provider)
    except ValueError as exc:
        raise AppError("INVALID_PROVIDER", str(exc), 400) from exc
    payload = build_history(instrument, retrieved_at=datetime.now(IST), provider_name=provider)
    status = 200 if payload.get("ok") else 422
    if payload.get("code") in {"HISTORICAL_SCHEMA_UNVERIFIED", "CANDLE_BOUNDARY_UNVERIFIED"}:
        status = 501
    return JSONResponse(status_code=status, content=payload)


def _feature_response(result: DatasetBuildResult | object) -> JSONResponse:
    if not isinstance(result, DatasetBuildResult):
        payload = result.model_dump(mode="json")
        status = 501 if payload.get("code") in {"HISTORICAL_SCHEMA_UNVERIFIED", "CANDLE_BOUNDARY_UNVERIFIED"} else 422
        return JSONResponse(status_code=status, content=payload)
    payload = result.model_dump(mode="json")
    return JSONResponse(status_code=200 if result.ok else 422, content=payload)


@app.post("/api/features/datasets")
def create_feature_dataset(
    body: FeatureDatasetBody,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    """Build an OHLC feature dataset from the named provider. No file path or URL is accepted."""
    require_csrf(request, settings)
    if body.as_of is not None and (body.as_of.tzinfo is None or body.as_of.tzinfo.utcoffset(body.as_of) is None):
        raise AppError("INVALID_TIMESTAMP", "as_of must be timezone-aware.", 422)
    try:
        assert_provider_name(body.provider)
    except ValueError as exc:
        raise AppError("INVALID_PROVIDER", str(exc), 400) from exc
    result = build_from_provider(
        body.instrument,
        provider_name=body.provider,
        retrieved_at=datetime.now(IST),
        as_of=body.as_of,
        store=feature_store(),
    )
    return _feature_response(result)


@app.get("/api/features/datasets/compare")
def compare_feature_datasets(
    left: str,
    right: str,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    store = feature_store()
    try:
        comparison = compare_manifests(store.read(left), store.read(right))
    except DatasetStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc
    return comparison


@app.get("/api/features/datasets/{dataset_id}")
def read_feature_dataset(
    dataset_id: str,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    try:
        return feature_store().read(dataset_id)
    except DatasetStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc


def _walk_response(result: dict) -> JSONResponse:
    status = 200 if result.get("ok") else 422
    if result.get("code") in {"HISTORICAL_SCHEMA_UNVERIFIED", "CANDLE_BOUNDARY_UNVERIFIED"}:
        status = 501
    payload = {
        "ok": result.get("ok"),
        "code": result.get("code"),
        "message": result.get("message"),
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "artifact": result.get("artifact"),
        "readiness": result.get("readiness"),
    }
    return JSONResponse(status_code=status, content=payload)


@app.post("/api/walk-forward")
def create_walk_forward(
    body: WalkForwardBody,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> JSONResponse:
    """Evaluate binary-1 on one configured provider. No file path or provider URL is accepted."""
    require_csrf(request, settings)
    try:
        assert_provider_name(body.provider)
        config = WalkForwardConfig(
            initial_train_size=body.initial_train_size,
            validation_size=body.validation_size,
            test_size=body.test_size,
            step_size=body.step_size,
            min_train=body.min_train,
            min_validation=body.min_validation,
            min_test=body.min_test,
        )
    except ValueError as exc:
        raise AppError("INVALID_PROVIDER", str(exc), 400) from exc
    result = run_from_provider(
        body.instrument,
        provider_name=body.provider,
        retrieved_at=datetime.now(IST),
        config=config,
    )
    return _walk_response(result)


@app.get("/api/walk-forward/{walkforward_id}")
def read_walk_forward(
    walkforward_id: str,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    try:
        artifact = walkforward_store().read(walkforward_id)
    except ExperimentStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc
    return artifact


@app.get("/api/audit")
def read_audit(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    read_session(request, settings)
    rows = session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(50)).all()
    return {
        "events": [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "entity": row.entity,
                "before": row.before,
                "after": row.after,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@app.post("/api/orders/live")
def refuse_live_order(
    body: LiveOrderBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Guard only. This route never imports a broker client."""
    require_csrf(request, settings)
    ensure_seed(session, settings)
    config = current_config(session)
    request_order(
        OperatingMode(config.runtime.mode),
        {"note": body.note},
        live_trading_enabled=config.runtime.live_trading_enabled,
        server_flag=settings.live_order_server_flag,
    )
    return {"placed": False}


@app.get("/api/research/paper-readiness")
def read_paper_readiness(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Audit the 8 readiness gates for paper trading."""
    read_session(request, settings)
    from app.research.paper_readiness_audit import audit_paper_trading_readiness
    report = audit_paper_trading_readiness(session)
    return report.model_dump()


@app.get("/api/forecasting/multi-asset/benchmark")
def read_multi_asset_benchmark(
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Read M40 multi-asset cross-validation and M41 factor attribution benchmarks."""
    read_session(request, settings)
    import json
    from app.settings import REPO_ROOT
    benchmark_file = REPO_ROOT / "var/datasets/m40_multi_asset_benchmark.json"
    attribution_file = REPO_ROOT / "var/datasets/m41_factor_attribution_results.json"
    benchmark_data = json.loads(benchmark_file.read_text(encoding="utf-8")) if benchmark_file.exists() else {}
    attribution_data = json.loads(attribution_file.read_text(encoding="utf-8")) if attribution_file.exists() else {}
    return {
        "benchmark": benchmark_data,
        "attribution": attribution_data,
    }


@app.get("/api/execution/multi-asset/simulation")
def read_multi_asset_simulation(
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Read M42 tax-accurate multi-asset paper trading simulation results."""
    read_session(request, settings)
    import json
    from app.settings import REPO_ROOT
    sim_file = REPO_ROOT / "var/datasets/m42_multi_asset_simulation_results.json"
    sim_data = json.loads(sim_file.read_text(encoding="utf-8")) if sim_file.exists() else {}
    return sim_data


@app.get("/api/forecasting/instruments")
def read_forecasting_instruments(
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Return configured primary tradable instruments with session status and metadata."""
    read_session(request, settings)
    from app.forecasting.instrument_hub import get_supported_instruments
    return {"instruments": get_supported_instruments()}


@app.get("/api/forecasting/instrument-forecast")
def read_instrument_forecast(
    request: Request,
    instrument: str = "NIFTY",
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Calculate or retrieve independent forecast and evidence for the requested instrument."""
    read_session(request, settings)
    from app.forecasting.instrument_hub import get_instrument_forecast
    return get_instrument_forecast(instrument)


@app.get("/api/forecasting/instrument-backtest")
def read_instrument_backtest(
    request: Request,
    instrument: str = "NIFTY",
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Retrieve independent walk-forward backtest report for the requested instrument."""
    read_session(request, settings)
    from app.forecasting.instrument_hub import get_instrument_backtest
    return get_instrument_backtest(instrument)


@app.get("/api/forecasting/live-trend-chart")
def get_live_trend_chart(
    request: Request,
    instrument: str = "NIFTY",
    bars: int = 35,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Retrieve historical candle bars combined with live forward projected trend and confidence cone."""
    read_session(request, settings)
    import json
    from datetime import datetime, timezone
    from app.errors import AppError
    from app.market.live_quotes import load_read
    from app.forecasting.instrument_hub import get_instrument_forecast

    inst = instrument.upper().strip()
    dataset_file = resolve_dataset_file(inst)
    if not dataset_file or not dataset_file.exists():
        raise AppError("DATASET_NOT_FOUND", f"Dataset for {inst} not found.", 400)

    try:
        raw_data = json.loads(dataset_file.read_text(encoding="utf-8"))
        all_candles = raw_data.get("candles") or []
        if not all_candles:
            raise AppError("EMPTY_CANDLES", "Candle list is empty.", 400)

        selected_candles = all_candles[-max(10, min(bars, 60)):]
        formatted_candles = []
        for c in selected_candles:
            time_str = str(c[0])
            label = time_str[-8:-3] if len(time_str) >= 8 else time_str
            formatted_candles.append({
                "time": label,
                "full_time": time_str,
                "open": round(float(c[1]), 2),
                "high": round(float(c[2]), 2),
                "low": round(float(c[3]), 2),
                "close": round(float(c[4]), 2),
                "volume": float(c[5]) if len(c) > 5 else 0.0,
            })

        read = load_read() or {}
        quotes = {q["instrument"]: q for q in read.get("quotes", []) if q.get("instrument")}
        commodities = {c["instrument"]: c for c in read.get("commodities", []) if c.get("instrument")}
        obs = {o["instrument"]: o for o in read.get("observations", []) if o.get("instrument")}

        q = quotes.get(inst) or commodities.get(inst) or obs.get(inst)
        if q and q.get("last_price") is not None:
            current_spot = round(float(q["last_price"]), 2)
            is_live = bool(q.get("is_live_quote", True))
        else:
            current_spot = formatted_candles[-1]["close"]
            is_live = False

        fc = get_instrument_forecast(inst)
        direction = fc.get("predicted_direction") or "BULLISH"
        decision = fc.get("decision") or "NO TRADE"
        calibrated_p = fc.get("calibrated_probability") or 0.53
        expected_move = fc.get("expected_return_points") or round(current_spot * 0.0035, 1)

        target = fc.get("target_spot")
        if target is None:
            if direction == "BULLISH" or decision == "BUY":
                target = round(current_spot + expected_move, 1)
            elif direction == "BEARISH" or decision == "SELL":
                target = round(current_spot - expected_move, 1)
            else:
                target = round(current_spot + expected_move * 0.2, 1)

        stop = fc.get("stop_loss_spot")
        if stop is None:
            if direction == "BULLISH" or decision == "BUY":
                stop = round(current_spot - expected_move * 0.7, 1)
            elif direction == "BEARISH" or decision == "SELL":
                stop = round(current_spot + expected_move * 0.7, 1)
            else:
                stop = round(current_spot - expected_move * 0.7, 1)

        target_delta = target - current_spot
        projected_path = []
        bar_steps = [
            ("+15m", 0.35, 0.50),
            ("+30m", 0.65, 0.75),
            ("+45m", 0.85, 0.90),
            ("+60m", 1.00, 1.00),
        ]
        for step_label, weight_target, weight_cone in bar_steps:
            pt_target = round(current_spot + (target_delta * weight_target), 2)
            cone_w = expected_move * weight_cone
            pt_upper = round(current_spot + cone_w, 2)
            pt_lower = round(current_spot - cone_w, 2)
            projected_path.append({
                "time": step_label,
                "projected_price": pt_target,
                "upper_bound": pt_upper,
                "lower_bound": pt_lower,
                "is_projection": True,
            })

        return {
            "ok": True,
            "instrument": inst,
            "current_spot": current_spot,
            "is_live": is_live,
            "decision": decision,
            "predicted_direction": direction,
            "calibrated_probability": calibrated_p,
            "expected_move_points": expected_move,
            "target_spot": target,
            "stop_loss_spot": stop,
            "candles": formatted_candles,
            "projected_path": projected_path,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        log.exception("Error generating live trend chart")
        return {"ok": False, "code": "CHART_ERROR", "message": str(exc)}


@app.get("/api/market/data-health")
def read_market_data_health(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Retrieve comprehensive data health, provenance, and session audits across instruments."""
    read_session(request, settings)
    from app.forecasting.instrument_hub import get_instrument_data_health
    return get_instrument_data_health(session)


class BenchmarkTrainRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    instrument: str = "NIFTY"
    model: str = "lightgbm"
    model_type: str | None = None
    strategy_mode: str = "regime_gated"
    interval: str = "M15"
    folds: int = 19


def resolve_dataset_file(inst: str) -> Path | None:
    sym = inst.upper().strip()
    if sym in {"NIFTY", "NSE-NIFTY", "NIFTY 50", "NIFTY50"}:
        p = REPO_ROOT / "var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json"
        return p if p.exists() else None
    elif sym in {"BANKNIFTY", "NSE-BANKNIFTY", "BANK NIFTY", "BANK"}:
        p = REPO_ROOT / "var/datasets/derived_banknifty_15m_m40.json"
        return p if p.exists() else None
    elif sym in {"SENSEX", "BSE-SENSEX"}:
        p = REPO_ROOT / "var/datasets/derived_sensex_15m.json"
        return p if p.exists() else None
    elif sym in {"CRUDEOILMINI", "MCX-CRUDEOILMINI", "CRUDE", "CRUDEOIL"}:
        p = REPO_ROOT / "var/datasets/derived_crude_15m.json"
        return p if p.exists() else None
    return None


def normalize_model_key(m: str) -> str:
    m = m.lower().strip()
    if "xgb" in m or "xgboost" in m:
        return "xgboost"
    elif "cat" in m or "catboost" in m:
        return "catboost"
    elif "dlinear" in m or "nlinear" in m:
        return "dlinear"
    elif "chronos" in m or "foundation" in m:
        return "chronos"
    elif "forest" in m or "rf" in m or "random" in m:
        return "random_forest"
    elif "mlp" in m or "neural" in m or "net" in m:
        return "mlp"
    elif "logist" in m or "l2" in m:
        return "logistic_regression"
    elif "prior" in m or "majority" in m or "base" in m:
        return "empirical_prior"
    elif "light" in m or "lgb" in m or "gbdt" in m:
        return "lightgbm"
    return "lightgbm"


@app.post("/api/forecasting/train-benchmark")
def train_and_benchmark_model(
    body: BenchmarkTrainRequest,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Train and run chronological walk-forward benchmark across model families and strategy modes."""
    read_session(request, settings)
    import json
    from datetime import timezone
    from app.errors import AppError
    from app.forecasting.m37_lightgbm_htf_research import run_m37_lightgbm_benchmark

    inst = body.instrument.upper().strip()
    dataset_file = resolve_dataset_file(inst)

    if not dataset_file or not dataset_file.exists():
        raise AppError(
            "DATASET_NOT_FOUND",
            f"Historical candle dataset for {inst} was not found on disk. Ingest the dataset first.",
            400,
        )

    try:
        data = json.loads(dataset_file.read_text(encoding="utf-8"))
        candles = data.get("candles") or []
        if not candles:
            raise AppError("EMPTY_CANDLES", "Dataset contains 0 candles.", 400)

        req_model = (body.model_type or body.model or "lightgbm").lower()
        model_key = normalize_model_key(req_model)

        req_mode = body.strategy_mode.lower()
        if "regime" in req_mode:
            mode_key = "regime_gated"
        elif "dead" in req_mode:
            mode_key = "deadband"
        else:
            mode_key = "raw"

        # Evaluate requested model plus empirical prior for reference
        models_to_run = list(dict.fromkeys([model_key, "empirical_prior"]))
        report = run_m37_lightgbm_benchmark(
            candles_15m=candles,
            dataset_id=data.get("dataset_id", inst),
            models_to_evaluate=models_to_run,
        )

        matching = None
        for s in report.strategies:
            if s.model_name == model_key and s.strategy_mode == mode_key:
                matching = s
                break
        if not matching and report.strategies:
            matching = report.strategies[0]

        all_summaries = []
        for s in report.strategies:
            all_summaries.append({
                "model_name": s.model_name,
                "strategy_mode": s.strategy_mode,
                "holdout_accuracy": round(s.holdout_accuracy, 4),
                "holdout_brier_skill_score": round(s.holdout_brier_skill_score, 4),
                "holdout_net_return_2bps": round(s.holdout_net_return_2bps, 2),
                "holdout_max_drawdown": round(s.holdout_max_drawdown_2bps, 2),
                "holdout_win_rate": round(s.holdout_win_rate, 4),
                "full_net_return_2bps": round(s.full_net_return_2bps, 2),
                "full_max_drawdown": round(s.full_max_drawdown_2bps, 2),
            })

        return {
            "ok": True,
            "instrument": inst,
            "model_name": matching.model_name if matching else model_key,
            "strategy_mode": matching.strategy_mode if matching else mode_key,
            "total_15m_candles": len(candles),
            "resampled_htf_candles": report.resampled_htf_candles,
            "total_aligned_rows": report.total_aligned_rows,
            "num_folds": report.num_folds,
            "dev_fold_count": report.dev_fold_count,
            "holdout_fold_count": report.holdout_fold_count,
            "holdout_accuracy": round(matching.holdout_accuracy, 4) if matching else 0.5,
            "holdout_brier_skill_score": round(matching.holdout_brier_skill_score, 4) if matching else 0.0,
            "holdout_net_return_2bps": round(matching.holdout_net_return_2bps, 2) if matching else 0.0,
            "holdout_max_drawdown": round(matching.holdout_max_drawdown_2bps, 2) if matching else 0.0,
            "holdout_win_rate": round(matching.holdout_win_rate, 4) if matching else 0.5,
            "full_net_return_2bps": round(matching.full_net_return_2bps, 2) if matching else 0.0,
            "full_max_drawdown": round(matching.full_max_drawdown_2bps, 2) if matching else 0.0,
            "all_strategies": all_summaries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        log.exception("benchmark training failed")
        return {"ok": False, "code": "TRAINING_ERROR", "message": f"{exc.__class__.__name__}: {str(exc)}"}


class MultiBenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    instruments: list[str] = Field(default_factory=lambda: ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOILMINI"])
    models: list[str] = Field(default_factory=lambda: ["lightgbm", "xgboost", "catboost", "random_forest", "mlp", "logistic_regression", "empirical_prior"])
    strategy_modes: list[str] = Field(default_factory=lambda: ["regime_gated", "deadband", "raw"])
    interval: str = "M15"
    folds: int = 19


@app.post("/api/forecasting/multi-benchmark")
def multi_instrument_model_benchmark(
    body: MultiBenchmarkRequest,
    request: Request,
    settings: Settings = Depends(settings_dep),
) -> dict:
    """Execute end-to-end multi-dataset and multi-model walk-forward benchmark and generate ranked leaderboard."""
    read_session(request, settings)
    import json
    from datetime import timezone
    from app.errors import AppError
    from app.forecasting.m37_lightgbm_htf_research import run_m37_lightgbm_benchmark, M37StrategyMode

    requested_instruments = body.instruments or ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOILMINI"]
    requested_models = [normalize_model_key(m) for m in (body.models or ["lightgbm", "xgboost", "catboost", "random_forest", "mlp", "logistic_regression", "empirical_prior"])]
    dedup_models = list(dict.fromkeys(requested_models))

    requested_modes = []
    for mode_str in (body.strategy_modes or ["regime_gated", "deadband", "raw"]):
        mode_l = mode_str.lower()
        if "regime" in mode_l:
            requested_modes.append(M37StrategyMode.REGIME_GATED)
        elif "dead" in mode_l:
            requested_modes.append(M37StrategyMode.DEADBAND)
        elif "raw" in mode_l:
            requested_modes.append(M37StrategyMode.RAW)
    if not requested_modes:
        requested_modes = [M37StrategyMode.REGIME_GATED, M37StrategyMode.DEADBAND, M37StrategyMode.RAW]

    leaderboard = []
    top_by_instrument = {}

    for inst in requested_instruments:
        dataset_file = resolve_dataset_file(inst)
        if not dataset_file or not dataset_file.exists():
            continue

        try:
            raw_data = json.loads(dataset_file.read_text(encoding="utf-8"))
            candles = raw_data.get("candles") or []
            if not candles:
                continue

            report = run_m37_lightgbm_benchmark(
                candles_15m=candles,
                dataset_id=raw_data.get("dataset_id", inst),
                models_to_evaluate=dedup_models,
                strategy_modes=requested_modes,
            )

            instrument_strategies = []
            for s in report.strategies:
                item = {
                    "instrument": inst.upper(),
                    "model_name": s.model_name,
                    "strategy_mode": s.strategy_mode,
                    "holdout_net_return_2bps": round(s.holdout_net_return_2bps, 2),
                    "holdout_accuracy": round(s.holdout_accuracy, 4),
                    "holdout_brier_skill_score": round(s.holdout_brier_skill_score, 4),
                    "holdout_win_rate": round(s.holdout_win_rate, 4),
                    "full_net_return_2bps": round(s.full_net_return_2bps, 2),
                    "full_max_drawdown": round(s.full_max_drawdown_2bps, 2),
                    "holdout_max_drawdown": round(s.holdout_max_drawdown_2bps, 2),
                    "turnover_units": round(s.holdout_turnover_units, 2),
                    "total_candles": len(candles),
                }
                leaderboard.append(item)
                instrument_strategies.append(item)

            if instrument_strategies:
                top_inst = max(instrument_strategies, key=lambda x: (x["holdout_net_return_2bps"], x["holdout_accuracy"]))
                top_by_instrument[inst.upper()] = top_inst
        except Exception as exc:
            log.warning("Benchmark error for %s: %s", inst, exc)
            continue

    if not leaderboard:
        raise AppError("BENCHMARK_EMPTY", "No valid datasets could be evaluated. Ensure datasets are pulled and available on disk.", 400)

    leaderboard.sort(key=lambda x: (x["holdout_net_return_2bps"], x["holdout_accuracy"], x["full_net_return_2bps"]), reverse=True)

    for rank_idx, row in enumerate(leaderboard, 1):
        row["rank"] = rank_idx

    overall_champion = leaderboard[0]
    highest_acc = max(leaderboard, key=lambda x: x["holdout_accuracy"])
    lowest_dd = min(leaderboard, key=lambda x: x["full_max_drawdown"])

    return {
        "ok": True,
        "total_combinations": len(leaderboard),
        "instruments_evaluated": list(top_by_instrument.keys()),
        "models_evaluated": dedup_models,
        "champion": overall_champion,
        "highest_accuracy_model": highest_acc,
        "lowest_drawdown_model": lowest_dd,
        "top_by_instrument": top_by_instrument,
        "leaderboard": leaderboard,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def create_app() -> FastAPI:
    reset_engine()
    get_settings.cache_clear()
    return app
