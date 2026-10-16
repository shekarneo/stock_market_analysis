"""Research routes for historical candle ingestion.

Import does not call Groww. A blocked contract returns a structured failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent
from app.errors import AppError
from app.features.service import feature_store
from app.forecasting.experiment import run_experiment
from app.forecasting.splits import SplitConfig
from app.forecasting.store import experiment_store
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward, walkforward_store
from app.integrations.groww import GrowwCallError
from app.integrations.http import HttpxCaller
from app.integrations.service import IntegrationError, groww_read_token
from app.market.history import (
    HistoryStoreError,
    capabilities,
    features_from_source,
    history_store,
    import_history,
    validate_request,
)
from app.market.retrieval import QuarantineStore, diagnostic_report
from app.market.live_quotes import load_read, run_live_read, save_read
from app.market.provenance import data_category
from app.market.schemas import IST
from app.settings import Settings, get_settings

router = APIRouter()


class LiveReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


class HistoryImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: str
    interval: str = "M15"
    start: datetime
    end: datetime
    provider: Literal["groww", "kite", "upstox", "angelone"] = "groww"


class ReconciliationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_a: Literal["groww", "kite", "upstox", "angelone"] = "groww"
    provider_b: Literal["groww", "kite", "upstox", "angelone"] = "upstox"
    instrument: str = "NIFTY"
    interval: str = "M15"
    tolerance: float = 2.0


class HistoryEvaluationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["m3", "m4"]
    require_verified_history: bool = False
    initial_train_size: int = 9
    validation_size: int = 5
    test_size: int = 4
    step_size: int = 4
    min_train: int = 8
    min_validation: int = 4
    min_test: int = 4


def _settings() -> Settings:
    return get_settings()


def quarantine_store() -> QuarantineStore:
    return QuarantineStore(history_store().root / "quarantine")


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


def _import_failure(code: str, message: str) -> dict:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "stored": False,
        "network_calls": 0,
        "candles": [],
        "quarantine": [],
        "states": {
            "request_sent": False,
            "raw_response_retrieved": False,
            "quality_passed": False,
            "timestamp_semantics_verified": False,
            "forecast_eligible": False,
        },
        "real_market_data_verified": False,
        "forecast_ready": False,
        "forecast_eligible": False,
        "paper_approved": False,
        "live_approved": False,
        "ingestion_operational": False,
    }


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise AppError("INVALID_TIMESTAMP", f"{name} must be timezone-aware.", 422)


@router.get("/api/history/capabilities")
def get_capabilities(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    return capabilities()


@router.get("/api/history/datasets")
def list_datasets(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    store = history_store()
    rows = []
    for dataset_id in store.list_ids():
        artifact = store.read(dataset_id)
        rows.append(
            {
                "dataset_id": artifact["dataset_id"],
                "instrument": artifact["instrument"],
                "interval": artifact["interval"],
                "origin": artifact["origin"],
                "data_category": data_category(artifact),
                "validation_status": artifact["validation"]["validation_status"],
                "forecast_eligible": artifact["forecast_eligible"],
                "real_market_data_verified": False,
                "candle_count": artifact["candle_count"],
            }
        )
    return {
        "datasets": rows,
        "ingestion_operational": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
    }


@router.get("/api/history/quarantine")
def list_quarantine(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    store = quarantine_store()
    stored = [store.read(quarantine_id) for quarantine_id in store.list_ids()]
    records = [
        diagnostic_report(record, [other for other in stored if other.get("quarantine_id") != record.get("quarantine_id")])
        for record in stored
    ]
    return {
        "records": records,
        "trusted_dataset_created": False,
        "forecast_eligible": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
    }


@router.get("/api/history/quarantine/{quarantine_id}")
def read_quarantine(quarantine_id: str, request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    try:
        store = quarantine_store()
        record = store.read(quarantine_id)
        siblings = [
            store.read(other_id)
            for other_id in store.list_ids()
            if other_id != quarantine_id
        ]
        return diagnostic_report(record, siblings)
    except HistoryStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc


@router.get("/api/history/datasets/{dataset_id}")
def read_dataset(dataset_id: str, request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    try:
        return history_store().read(dataset_id)
    except HistoryStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc


@router.post("/api/history/imports")
def create_import(
    body: HistoryImportBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    principal = require_csrf(request, settings)
    _aware(body.start, "start")
    _aware(body.end, "end")
    caller = HttpxCaller()
    try:
        validate_request(body.instrument, body.interval, body.start, body.end)
        if body.provider == "groww":
            token = groww_read_token(session, settings, caller)
            result = import_history(
                body.instrument,
                interval=body.interval,
                start=body.start,
                end=body.end,
                caller=caller,
                access_token=token,
                quarantine=QuarantineStore(history_store().root / "quarantine"),
            )
        else:
            from app.market.independent_provider import IndependentProviderAdapter, ProviderCandleRequest, resolve_credentials_safe
            creds, missing = resolve_credentials_safe(body.provider)
            if not creds:
                result = _import_failure(
                    "BLOCKED_CREDENTIALS_MISSING",
                    f"Credentials for independent provider '{body.provider}' are missing or unconfigured: {missing}. Data acquisition is blocked.",
                )
                result["provider"] = body.provider
            else:
                adapter = IndependentProviderAdapter(provider=body.provider)
                req = ProviderCandleRequest(
                    instrument=body.instrument,
                    interval=body.interval,
                    from_date=body.start.date(),
                    to_date=body.end.date(),
                )
                res = adapter.fetch_reference_dataset(req, credentials=creds)
                if not res.get("ok"):
                    result = _import_failure(res.get("code", "PROVIDER_FETCH_ERROR"), res.get("message", "Fetch failed"))
                    result["provider"] = body.provider
                else:
                    result = {
                        "ok": True,
                        "code": res.get("code", "STORED"),
                        "message": f"Successfully acquired and quarantined {res.get('total_candles', 0)} candles from {body.provider}.",
                        "provider": body.provider,
                        "stored": True,
                        "network_calls": 1,
                        "candles": res.get("normalized_candles", []),
                        "quarantine": [{"quarantine_id": res.get("raw_sha256"), "path": res.get("quarantine_path")}],
                        "states": {
                            "request_sent": True,
                            "raw_response_retrieved": True,
                            "quality_passed": True,
                            "timestamp_semantics_verified": True,
                            "forecast_eligible": True,
                        },
                        "real_market_data_verified": False,
                        "forecast_ready": False,
                        "forecast_eligible": True,
                        "paper_approved": False,
                        "live_approved": False,
                        "ingestion_operational": False,
                    }
    except (HistoryStoreError, IntegrationError, GrowwCallError) as exc:
        result = _import_failure(exc.code, exc.message)
    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="history.import",
            entity=body.instrument,
            before=None,
            after={"code": result["code"], "network_calls": result.get("network_calls", 0), "provider": body.provider},
        )
    )
    status = 422 if result["code"] not in {"UNMAPPED_INSTRUMENT", "REMOVED_INSTRUMENT", "UNKNOWN_INSTRUMENT", "INVALID_RANGE", "UNSUPPORTED_INTERVAL", "BEFORE_DOCUMENTED_HISTORY", "RANGE_TOO_LONG"} else 400
    return JSONResponse(status_code=status, content=result)


@router.post("/api/history/reconcile")
def post_history_reconcile(
    body: ReconciliationRequestBody,
    request: Request,
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    require_csrf(request, settings)
    from app.market.independent_provider import reconcile_providers_pairwise
    from app.market.session_calendar import run_independent_verification_audit

    store = history_store()
    dataset_ids = store.list_ids()
    candles_a = []
    candles_b = []
    for d_id in dataset_ids:
        art = store.read(d_id)
        if art.get("origin") == f"provider_{body.provider_a}" or (body.provider_a == "groww" and art.get("origin") == "provider_groww"):
            candles_a = art.get("candles") or []
        if art.get("origin") == f"provider_{body.provider_b}" or (body.provider_b == "groww" and art.get("origin") == "provider_groww"):
            candles_b = art.get("candles") or []

    if not candles_a or not candles_b:
        audit_res = run_independent_verification_audit()
        report = {
            "ok": False,
            "status": "DATA_UNAVAILABLE_FOR_RECONCILIATION",
            "provider_a": body.provider_a,
            "provider_b": body.provider_b,
            "tolerance": body.tolerance,
            "message": f"Historical candle series for {body.provider_a} or {body.provider_b} are not both available in the local repository.",
            "verification_audit": audit_res,
        }
        return JSONResponse(status_code=422, content=report)

    recon_report = reconcile_providers_pairwise(
        candles_a,
        candles_b,
        provider_a_name=body.provider_a,
        provider_b_name=body.provider_b,
        tolerance=body.tolerance,
    )
    status_code = 200 if recon_report.get("ok") else 422
    return JSONResponse(status_code=status_code, content=recon_report)


@router.get("/api/history/reconcile/status")
def get_reconcile_status(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    from app.market.session_calendar import run_independent_verification_audit
    return run_independent_verification_audit()


@router.post("/api/history/datasets/{dataset_id}/evaluations")
def evaluate_dataset(
    dataset_id: str,
    body: HistoryEvaluationBody,
    request: Request,
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    require_csrf(request, settings)
    try:
        source = history_store().read(dataset_id)
    except HistoryStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc
    if source.get("real_market_data_verified") is True:
        raise AppError("VERIFICATION_REFUSED", "Verification status cannot be set on a historical dataset.", 422)
    if not source.get("forecast_eligible"):
        raise AppError(
            "DATASET_REJECTED",
            "This dataset is not eligible for forecasting evaluation.",
            422,
        )
    built = features_from_source(source, feature_store=feature_store())
    if not built["ok"] or built["artifact"] is None:
        raise AppError(built["code"] or "DATASET_REJECTED", built["message"], 422)
    feature_artifact = built["artifact"]
    if body.kind == "m3":
        result = run_experiment(
            feature_artifact,
            config=SplitConfig(
                min_train=body.min_train,
                min_validation=body.min_validation,
                min_test=body.min_test,
            ),
            require_verified_history=body.require_verified_history,
        )
        if result.get("ok") and result.get("artifact") is not None:
            experiment_store().write(result["artifact"])
    else:
        try:
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
            raise AppError("INVALID_CONFIG", str(exc), 422) from exc
        result = run_walk_forward(
            feature_artifact,
            config=config,
            require_verified_history=body.require_verified_history,
        )
        if result.get("ok") and result.get("artifact") is not None:
            walkforward_store().write(result["artifact"])
    payload = {
        "ok": result.get("ok"),
        "code": result.get("code"),
        "message": result.get("message"),
        "data_category": data_category(feature_artifact),
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "artifact": result.get("artifact"),
    }
    return JSONResponse(status_code=200 if result.get("ok") else 422, content=payload)


@router.post("/api/forecasting/compare")
def post_model_comparison(
    request: Request,
    body: dict,
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    require_csrf(request, settings)
    from app.forecasting.comparison import ModelComparisonRequest, compare_quantitative_models
    req = ModelComparisonRequest(**body)
    try:
        source = history_store().read(req.dataset_id)
    except HistoryStoreError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise AppError(exc.code, exc.message, status) from exc

    built = features_from_source(source, feature_store=feature_store())
    if not built["ok"] or built["artifact"] is None:
        raise AppError(built["code"] or "DATASET_REJECTED", built["message"], 422)

    cfg = WalkForwardConfig(
        initial_train_size=req.initial_train_size,
        validation_size=req.validation_size,
        test_size=req.test_size,
        step_size=req.step_size,
        embargo_bars=req.embargo_bars,
        seed=req.seed,
    )
    result = compare_quantitative_models(built["artifact"], config=cfg)
    return JSONResponse(status_code=200 if result.get("ok") else 422, content=result)


@router.get("/api/market/live-quotes")
def live_quotes(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    stored = load_read()
    now_ist = datetime.now(timezone.utc)
    from app.market.session_intelligence import build_cross_market_snapshot, generate_post_close_analysis

    if stored is None:
        cross_snapshot = build_cross_market_snapshot([], [], [], [], as_of=now_ist)
        post_close = generate_post_close_analysis(cross_snapshot, as_of=now_ist) if cross_snapshot["post_close_mode"] else None
        return {
            "status": "NOT_READ",
            "quotes": [],
            "commodities": [],
            "global_indices": [],
            "sectoral_indices": [],
            "cross_market_snapshot": cross_snapshot,
            "post_close_mode": cross_snapshot["post_close_mode"],
            "is_equity_open": cross_snapshot["is_equity_open"],
            "is_commodity_open": cross_snapshot["is_commodity_open"],
            "post_close_analysis": post_close,
            "message": "No Groww quote read is stored.",
            "real_market_data_verified": False,
        }
    commodities = stored.get("commodities") or []
    global_indices = stored.get("global_indices") or []
    sectoral_indices = stored.get("sectoral_indices") or []

    # Check if snapshot feeds are missing or older than 60s
    needs_refresh = not commodities or not sectoral_indices or not global_indices or request.query_params.get("refresh") == "true"
    if not needs_refresh and commodities:
        try:
            first_stamp = commodities[0].get("retrieved_at")
            if first_stamp:
                first_dt = datetime.fromisoformat(first_stamp.replace("Z", "+00:00"))
                now_utc = datetime.now(timezone.utc)
                if (now_utc - first_dt).total_seconds() > 15:
                    needs_refresh = True
        except Exception:
            pass

    if needs_refresh:
        try:
            from app.market.groww_market_snapshot import (
                build_groww_market_observations,
                parse_global_indices,
                parse_mcx_commodities,
                parse_sectoral_indices,
            )
            fresh_comm = parse_mcx_commodities()
            if fresh_comm:
                commodities = fresh_comm
                stored["commodities"] = commodities
            fresh_global = parse_global_indices()
            if fresh_global:
                global_indices = fresh_global
                stored["global_indices"] = global_indices
            fresh_sec = parse_sectoral_indices()
            if fresh_sec:
                sectoral_indices = fresh_sec
                stored["sectoral_indices"] = sectoral_indices

            base_obs = stored.get("observations") or []
            extra_obs = build_groww_market_observations(commodities, global_indices, sectoral_indices)
            seen_inst = set()
            merged_obs = []
            for o in base_obs + extra_obs:
                inst = o.get("instrument")
                if inst and inst not in seen_inst:
                    seen_inst.add(inst)
                    merged_obs.append(o)
            stored["observations"] = merged_obs
            save_read(stored)
        except Exception:
            pass

    quotes_list = [q for q in (stored.get("quotes") or []) if q.get("instrument") in ("NIFTY", "SENSEX")]

    cross_snapshot = build_cross_market_snapshot(quotes_list, commodities, global_indices, sectoral_indices, as_of=now_ist)
    post_close = generate_post_close_analysis(cross_snapshot, as_of=now_ist) if cross_snapshot["post_close_mode"] else None

    from app.market.poller import get_poll_config
    return {
        "status": stored.get("status") or "READ",
        "quotes": quotes_list,
        "commodities": commodities,
        "global_indices": global_indices,
        "sectoral_indices": sectoral_indices,
        "cross_market_snapshot": cross_snapshot,
        "post_close_mode": cross_snapshot["post_close_mode"],
        "is_equity_open": cross_snapshot["is_equity_open"],
        "is_commodity_open": cross_snapshot["is_commodity_open"],
        "post_close_analysis": post_close,
        "errors": stored.get("errors") or [],
        "message": stored.get("message"),
        "retrieved_at": (quotes_list or [{}])[0].get("retrieved_at") if quotes_list else None,
        "real_market_data_verified": False,
        "candles_requested": False,
        "poll_config": get_poll_config(),
    }


@router.post("/api/market/live-quotes")
def read_live_quotes(
    body: LiveReadBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    if body.confirm is not True:
        raise AppError("CONFIRMATION_REQUIRED", "The live read requires confirm true. No request was sent.", 422)
    caller = HttpxCaller()
    from app.market.poller import perform_live_sync
    result = perform_live_sync(session, settings, caller=caller)

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="market.live_read",
            entity="groww-live-quote",
            before=None,
            after={
                "status": result.get("status"),
                "network_calls": result.get("network_calls"),
                "instruments": [item.get("instrument") for item in result.get("quotes") or []],
            },
        )
    )
    public = {key: value for key, value in result.items() if key != "observations"}
    public["real_market_data_verified"] = False
    return public


@router.get("/api/market/poll-config")
def get_poll_config_endpoint(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    from app.market.poller import get_poll_config
    return get_poll_config()


class PollConfigBody(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None


@router.post("/api/market/poll-config")
def update_poll_config_endpoint(
    body: PollConfigBody,
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    require_csrf(request, settings)
    from app.market.poller import update_poll_config
    return update_poll_config(enabled=body.enabled, interval_seconds=body.interval_seconds)

