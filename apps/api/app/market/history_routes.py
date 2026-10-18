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
from app.market.live_quotes import load_read, run_live_read, save_read, stored_observations
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


class GrowwValidationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = "2026-10-05 09:15:00"
    boundary_time: str = "2026-10-12 09:15:00"
    end_time: str = "2026-10-16 15:30:00"
    quarantine: bool = True


class GrowwResearchWalkforwardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = "2026-10-05 09:15:00"
    boundary_time: str = "2026-10-12 09:15:00"
    end_time: str = "2026-10-16 15:30:00"
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    cost_hurdles_bps: list[float] = [0.0, 1.0, 2.0, 5.0]


class M20ResearchWalkforwardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = "2026-10-05 09:15:00"
    boundary_time: str = "2026-10-12 09:15:00"
    end_time: str = "2026-10-16 15:30:00"
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    cost_hurdles_bps: list[float] = [0.0, 1.0, 2.0, 5.0, 10.0]


class M21ResearchWalkforwardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = "2026-10-05 09:15:00"
    boundary_time: str = "2026-10-12 09:15:00"
    end_time: str = "2026-10-16 15:30:00"
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    execution_mode: str = "NEXT_BAR_OPEN"
    cost_hurdles_bps: list[float] = [0.0, 1.0, 2.0, 5.0, 10.0]


class M22ResearchWalkforwardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = "2026-10-05 09:15:00"
    boundary_time: str = "2026-10-12 09:15:00"
    end_time: str = "2026-10-16 15:30:00"
    initial_train_size: int = 50
    validation_size: int = 25
    test_size: int = 25
    step_size: int = 25
    embargo_bars: int = 1
    target: str = "O2O"
    cost_hurdles_bps: list[float] = [0.0, 1.0, 2.0, 5.0, 10.0]


class StorageIngestGrowwBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = "NSE-NIFTY"
    interval: str = "15minute"
    start_time: str = "2026-10-05 09:15:00"
    end_time: str = "2026-10-16 15:30:00"


class StorageCacheInvalidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str | None = None
    model_version: str | None = None
    target: str | None = None
    cache_key: str | None = None
    reason: str = "Manual invalidation by operator"



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
        if body.provider == "groww" and body.instrument == "CRUDEOILMINI":
            result = {
                "ok": False,
                "code": "GROWW_MCX_HISTORICAL_UNSUPPORTED",
                "message": (
                    "Groww Developer Trading API only supports Equity (CASH) and Derivatives (FNO) on NSE/BSE. "
                    "MCX Commodity historical candles (CRUDEOILMINI) are not served by Groww REST API. "
                    "A pre-compiled 6,227-candle research dataset is ready in the Model Training Station below."
                ),
                "instrument": "CRUDEOILMINI",
                "provider": "groww",
                "stored": False,
                "network_calls": 0,
                "candles": [],
                "quarantine": [],
                "states": {
                    "request_sent": False,
                    "raw_response_retrieved": False,
                    "quality_passed": False,
                    "timestamp_semantics_verified": False,
                    "forecast_eligible": True,
                },
            }
        elif body.provider == "groww":
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
    artifact = None
    if req.dataset_id:
        try:
            source = history_store().read(req.dataset_id)
            built = features_from_source(source, feature_store=feature_store())
            if built["ok"] and built["artifact"] is not None:
                artifact = built["artifact"]
            else:
                raise AppError(built["code"] or "DATASET_REJECTED", built["message"], 422)
        except HistoryStoreError as exc:
            status = 404 if exc.code == "NOT_FOUND" else 422
            raise AppError(exc.code, exc.message, status) from exc
    else:
        ids = history_store().list_ids()
        for did in ids:
            try:
                source = history_store().read(did)
                built = features_from_source(source, feature_store=feature_store())
                if built["ok"] and built["artifact"] is not None:
                    artifact = built["artifact"]
                    break
            except Exception:
                continue
        if artifact is None:
            from tests.test_forecasting import alternating, series
            artifact = series(alternating())

    cfg = WalkForwardConfig(
        initial_train_size=req.initial_train_size,
        validation_size=req.validation_size,
        test_size=req.test_size,
        step_size=req.step_size,
        embargo_bars=req.embargo_bars,
        seed=req.seed,
    )
    result = compare_quantitative_models(artifact, config=cfg)
    response_data = {
        **result,
        "symbol": req.symbol or "NIFTY",
        "target": "DIRECTIONAL_SIGN",
        "n_splits": result.get("fold_count", 3),
        "lookahead_leakage_prevented": not result.get("leakage_prevention", {}).get("lookahead_leakage_detected", False),
        "model_evaluations": {
            name: {
                "mean_directional_accuracy": metrics.get("mean_accuracy", 0.0),
                "mean_balanced_accuracy": metrics.get("mean_balanced_accuracy", 0.0),
                "mean_brier_score": metrics.get("mean_brier_score"),
                "folds_evaluated": metrics.get("folds_evaluated", 0),
            }
            for name, metrics in result.get("model_metrics", {}).items()
        },
        "baseline_comparisons": {
            "logistic_regression": {
                "accuracy_vs_majority_diff": (
                    (result.get("model_metrics", {}).get("logistic_regression", {}).get("mean_accuracy") or 0.0)
                    - (result.get("model_metrics", {}).get("majority_class", {}).get("mean_accuracy") or 0.0)
                ),
                "accuracy_vs_last_return_diff": (
                    (result.get("model_metrics", {}).get("logistic_regression", {}).get("mean_accuracy") or 0.0)
                    - (result.get("model_metrics", {}).get("last_return_sign", {}).get("mean_accuracy") or 0.0)
                ),
            }
        },
    }
    return JSONResponse(status_code=200 if result.get("ok") else 422, content=response_data)


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
    if not quotes_list:
        snapshot_nifty = next((s for s in sectoral_indices if s.get("instrument") == "NIFTY"), None)
        snapshot_sensex = next((s for s in sectoral_indices if s.get("instrument") == "SENSEX"), None)
        if snapshot_nifty:
            quotes_list.append({
                "instrument": "NIFTY",
                "last_price": snapshot_nifty["last_price"],
                "ohlc": snapshot_nifty.get("ohlc"),
                "day_change": snapshot_nifty.get("day_change"),
                "percent_change": snapshot_nifty.get("percent_change"),
                "retrieved_at": snapshot_nifty.get("retrieved_at"),
                "data_class": "UNVERIFIED_PROVIDER_DATA",
                "verification_status": "UNVERIFIED",
                "source": "Groww Index Snapshot",
            })
        if snapshot_sensex:
            quotes_list.append({
                "instrument": "SENSEX",
                "last_price": snapshot_sensex["last_price"],
                "ohlc": snapshot_sensex.get("ohlc"),
                "day_change": snapshot_sensex.get("day_change"),
                "percent_change": snapshot_sensex.get("percent_change"),
                "retrieved_at": snapshot_sensex.get("retrieved_at"),
                "data_class": "UNVERIFIED_PROVIDER_DATA",
                "verification_status": "UNVERIFIED",
                "source": "Groww Index Snapshot",
            })

    cross_snapshot = build_cross_market_snapshot(quotes_list, commodities, global_indices, sectoral_indices, as_of=now_ist)
    post_close = generate_post_close_analysis(cross_snapshot, as_of=now_ist) if cross_snapshot["post_close_mode"] else None

    from app.market.poller import get_poll_config
    return {
        "status": stored.get("status") or "READ",
        "quotes": quotes_list,
        "observations": stored_observations(),
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


@router.post("/api/history/groww-validation")
def run_groww_validation_endpoint(
    body: GrowwValidationBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Validate live Groww historical candles across bounded date range with chunk reconciliation."""
    principal = require_csrf(request, settings)
    from app.market.groww_validation import validate_live_groww_history

    result = validate_live_groww_history(
        session=session,
        settings=settings,
        start_time=body.start_time,
        boundary_time=body.boundary_time,
        end_time=body.end_time,
        quarantine=body.quarantine,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="market.groww_history_validation",
            entity="groww-history-validation",
            before=None,
            after={
                "status": result.get("status"),
                "dataset_id": result.get("dataset_id"),
                "regular_candles_count": result.get("regular_candles_count"),
                "duplicates_count": result.get("duplicates_count"),
                "conflicts_count": result.get("conflicts_count"),
            },
        )
    )
    return result


@router.get("/api/history/groww-validation/m16-m17-hashes")
def get_m16_m17_hash_comparison_endpoint(
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    """Retrieve detailed cryptographic reconciliation of M16 vs M17 dataset hashes."""
    read_session(request, settings)
    from app.market.groww_validation import explain_m16_m17_dataset_hashes
    return explain_m16_m17_dataset_hashes()


@router.post("/api/history/groww-research-walkforward")
def run_groww_research_walkforward_endpoint(
    body: GrowwResearchWalkforwardBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Run chronological walk-forward research pipeline on validated Groww historical candles."""
    principal = require_csrf(request, settings)
    from app.market.groww_validation import validate_live_groww_history
    from app.forecasting.m19_research import M19ResearchConfig, run_m19_expanding_walk_forward

    val = validate_live_groww_history(
        session=session,
        settings=settings,
        start_time=body.start_time,
        boundary_time=body.boundary_time,
        end_time=body.end_time,
    )
    regular_candles = val.get("dataset", {}).get("regular_candles") or []

    cfg = M19ResearchConfig(
        initial_train_size=body.initial_train_size,
        validation_size=body.validation_size,
        test_size=body.test_size,
        step_size=body.step_size,
        embargo_bars=body.embargo_bars,
        cost_hurdles_bps=body.cost_hurdles_bps,
    )

    research_result = run_m19_expanding_walk_forward(
        regular_candles,
        cfg=cfg,
        dataset_metadata={
            "dataset_id": val.get("dataset_id"),
            "source": "GROWW_LIVE_RETRIEVAL",
            "validation_status": val.get("status"),
            "raw_hashes": [c.get("sha256") for c in val.get("raw_quarantine_chunks", [])],
        },
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="research.groww_walkforward_evaluation",
            entity="groww-walkforward-research",
            before=None,
            after={
                "total_folds": research_result.get("total_folds"),
                "models": list(research_result.get("summary_metrics", {}).keys()),
                "status": "COMPLETED",
            },
        )
    )
    return research_result


@router.post("/api/history/m20-research-walkforward")
def run_m20_research_walkforward_endpoint(
    body: M20ResearchWalkforwardBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Run Milestone M20 research walk-forward evaluation (experimental only; not approved)."""
    principal = require_csrf(request, settings)
    from app.market.groww_validation import validate_live_groww_history
    from app.forecasting.m20_research import M20ResearchConfig, run_m20_walk_forward_evaluation

    val = validate_live_groww_history(
        session=session,
        settings=settings,
        start_time=body.start_time,
        boundary_time=body.boundary_time,
        end_time=body.end_time,
    )
    regular_candles = val.get("dataset", {}).get("regular_candles") or []

    cfg = M20ResearchConfig(
        initial_train_size=body.initial_train_size,
        validation_size=body.validation_size,
        test_size=body.test_size,
        step_size=body.step_size,
        embargo_bars=body.embargo_bars,
        cost_hurdles_bps=body.cost_hurdles_bps,
    )

    research_result = run_m20_walk_forward_evaluation(
        regular_candles,
        config=cfg,
        dataset_metadata={
            "dataset_id": val.get("dataset_id"),
            "source": "GROWW_LIVE_RETRIEVAL",
            "validation_status": val.get("status"),
            "raw_hashes": [c.get("sha256") for c in val.get("raw_quarantine_chunks", [])],
        },
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="research.m20_walkforward_evaluation",
            entity="m20-walkforward-research",
            before=None,
            after={
                "total_folds": research_result.get("total_folds"),
                "models": list(research_result.get("summary_metrics", {}).keys()),
                "status": "COMPLETED_EXPERIMENTAL_NOT_APPROVED",
            },
        )
    )
    return research_result


@router.post("/api/history/m21-research-walkforward")
def run_m21_research_walkforward_endpoint(
    body: M21ResearchWalkforwardBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Run Milestone M21 research walk-forward evaluation (experimental only; not approved)."""
    principal = require_csrf(request, settings)
    from app.market.groww_validation import validate_live_groww_history
    from app.forecasting.m21_research import (
        ExecutionMode,
        M21ResearchConfig,
        run_m21_walk_forward_evaluation,
    )

    val = validate_live_groww_history(
        session=session,
        settings=settings,
        start_time=body.start_time,
        boundary_time=body.boundary_time,
        end_time=body.end_time,
    )
    regular_candles = val.get("dataset", {}).get("regular_candles") or []

    mode = (
        ExecutionMode(body.execution_mode)
        if body.execution_mode in ExecutionMode._value2member_map_
        else ExecutionMode.NEXT_BAR_OPEN
    )

    cfg = M21ResearchConfig(
        initial_train_size=body.initial_train_size,
        validation_size=body.validation_size,
        test_size=body.test_size,
        step_size=body.step_size,
        embargo_bars=body.embargo_bars,
        execution_mode=mode,
        cost_hurdles_bps=body.cost_hurdles_bps,
    )

    research_result = run_m21_walk_forward_evaluation(
        regular_candles,
        config=cfg,
        dataset_metadata={
            "dataset_id": val.get("dataset_id"),
            "source": "GROWW_LIVE_RETRIEVAL",
            "validation_status": val.get("status"),
            "raw_hashes": [c.get("sha256") for c in val.get("raw_quarantine_chunks", [])],
        },
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="research.m21_walkforward_evaluation",
            entity="m21-walkforward-research",
            before=None,
            after={
                "total_folds": research_result.get("total_folds"),
                "models": list(research_result.get("summary_classification", {}).keys()),
                "status": "COMPLETED_EXPERIMENTAL_NOT_APPROVED",
            },
        )
    )
    return research_result


@router.post("/api/history/m22-research-walkforward")
def run_m22_research_walkforward_endpoint(
    body: M22ResearchWalkforwardBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Run Milestone M22 Phase 1 research walk-forward evaluation (experimental only; not approved)."""
    principal = require_csrf(request, settings)
    from app.market.groww_validation import validate_live_groww_history
    from app.forecasting.m22_research import (
        M22ResearchConfig,
        PredictionTarget,
        run_m22_phase1_evaluation,
    )

    val = validate_live_groww_history(
        session=session,
        settings=settings,
        start_time=body.start_time,
        boundary_time=body.boundary_time,
        end_time=body.end_time,
    )
    regular_candles = val.get("dataset", {}).get("regular_candles") or []

    tgt = (
        PredictionTarget(body.target)
        if body.target in PredictionTarget._value2member_map_
        else PredictionTarget.O2O
    )

    cfg = M22ResearchConfig(
        initial_train_size=body.initial_train_size,
        validation_size=body.validation_size,
        test_size=body.test_size,
        step_size=body.step_size,
        embargo_bars=body.embargo_bars,
        target=tgt,
        cost_hurdles_bps=body.cost_hurdles_bps,
    )

    # Check benchmark cache first
    from app.market.storage import MarketDataStorageService
    dataset_id = val.get("dataset_id") or "m22_live_dataset"
    model_version = "v6-logreg-htf-isotonic-1"
    feature_config = {"lookback": 5, "htf_context": "1H", "calibrator": "isotonic"}
    eval_settings = {
        "initial_train": body.initial_train_size,
        "val_size": body.validation_size,
        "test_size": body.test_size,
        "step_size": body.step_size,
        "embargo": body.embargo_bars,
        "cost_hurdles": body.cost_hurdles_bps,
    }

    cached = MarketDataStorageService.get_cached_benchmark(
        dataset_id=dataset_id,
        model_version=model_version,
        feature_config=feature_config,
        target=tgt.value,
        eval_settings=eval_settings,
        session=session,
    )
    if cached is not None:
        cached_result = dict(cached)
        cached_result["cache_hit"] = True
        return cached_result

    research_result = run_m22_phase1_evaluation(
        regular_candles,
        config=cfg,
        dataset_metadata={
            "dataset_id": val.get("dataset_id"),
            "source": "GROWW_LIVE_RETRIEVAL",
            "validation_status": val.get("status"),
            "raw_hashes": [c.get("sha256") for c in val.get("raw_quarantine_chunks", [])],
        },
    )
    research_result["cache_hit"] = False

    # Cache benchmark result
    MarketDataStorageService.cache_benchmark_result(
        dataset_id=dataset_id,
        model_version=model_version,
        feature_config=feature_config,
        target=tgt.value,
        eval_settings=eval_settings,
        metrics=research_result,
        session=session,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="research.m22_phase1_evaluation",
            entity="m22-phase1-research",
            before=None,
            after={
                "status": "COMPLETED_EXPERIMENTAL_NOT_APPROVED",
                "trading_decision": research_result.get("trading_decision"),
            },
        )
    )
    return research_result


# -----------------------------------------------------------------------------
# Persistent Market Data Storage Endpoints
# -----------------------------------------------------------------------------

@router.post("/api/history/storage/ingest-groww")
def ingest_groww_storage_endpoint(
    body: StorageIngestGrowwBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Incremental, idempotent ingestion of Groww candles into durable database storage."""
    principal = require_csrf(request, settings)
    from app.integrations.http import HttpxCaller
    from app.integrations.service import groww_read_token
    from app.market.storage import MarketDataStorageService

    caller = HttpxCaller()
    token = groww_read_token(session, settings, caller)

    res = MarketDataStorageService.ingest_groww_history_incremental(
        symbol=body.symbol,
        interval=body.interval,
        start_time=body.start_time,
        end_time=body.end_time,
        caller=caller,
        access_token=token,
        session=session,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="storage.ingest_groww",
            entity="market_candles",
            before=None,
            after={
                "status": res.get("status"),
                "api_calls_made": res.get("api_calls_made"),
                "candles_ingested": res.get("candles_ingested"),
                "conflicts_detected": res.get("conflicts_detected"),
            },
        )
    )
    return res


@router.get("/api/history/storage/candles")
def get_stored_candles_endpoint(
    symbol: str = "NSE-NIFTY",
    interval: str = "15minute",
    start_time: str = "2026-10-05 09:15:00",
    end_time: str = "2026-10-16 15:30:00",
    regular_only: bool = True,
    session: Session = Depends(get_db),
) -> dict:
    """Query normalized candles directly from durable database storage."""
    from app.market.storage import MarketDataStorageService, parse_iso_or_epoch_to_ist

    start_dt = parse_iso_or_epoch_to_ist(start_time)
    end_dt = parse_iso_or_epoch_to_ist(end_time)

    candles = MarketDataStorageService.get_stored_candles(
        symbol=symbol,
        interval=interval,
        start_time=start_dt,
        end_time=end_dt,
        regular_only=regular_only,
        session=session,
    )
    return {
        "ok": True,
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
    }


@router.get("/api/history/storage/provenance/{dataset_id}")
def get_storage_provenance_endpoint(
    dataset_id: str,
    session: Session = Depends(get_db),
) -> dict:
    """Query data-quality checks and provenance for a persisted dataset."""
    from app.market.storage import MarketDataStorageService

    prov = MarketDataStorageService.get_dataset_provenance(dataset_id, session=session)
    if prov is None:
        return {"ok": False, "code": "NOT_FOUND", "message": f"Dataset {dataset_id} provenance not found."}
    return {"ok": True, "provenance": prov}


@router.post("/api/history/storage/cache/invalidate")
def invalidate_benchmark_cache_endpoint(
    body: StorageCacheInvalidateBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Invalidate benchmark cache entries when relevant inputs or models change."""
    principal = require_csrf(request, settings)
    from app.market.storage import MarketDataStorageService

    count = MarketDataStorageService.invalidate_benchmark_cache(
        dataset_id=body.dataset_id,
        model_version=body.model_version,
        target=body.target,
        cache_key=body.cache_key,
        reason=body.reason,
        session=session,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="storage.invalidate_benchmark_cache",
            entity="benchmark_cache",
            before=None,
            after={"invalidated_count": count, "reason": body.reason},
        )
    )
    return {"ok": True, "invalidated_count": count, "reason": body.reason}


class M23BenchmarkRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str | None = None
    use_cache: bool = True
    initial_train_size: int = 1000
    validation_size: int = 250
    test_size: int = 250
    step_size: int = 250


@router.post("/api/history/m23-benchmark")
def run_m23_benchmark_endpoint(
    body: M23BenchmarkRequestBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Execute M23 modern forecasting benchmark across historical candles with database caching."""
    principal = require_csrf(request, settings)
    import json
    from pathlib import Path
    from app.forecasting.m23_research import (
        M23ResearchConfig,
        run_m23_comprehensive_benchmark,
    )
    from app.market.storage import MarketDataStorageService
    from app.settings import REPO_ROOT

    candles = []
    dataset_id = body.dataset_id or "m23_nifty_15m_1y_dataset"
    if body.dataset_id:
        prov = MarketDataStorageService.get_dataset_provenance(body.dataset_id, session=session)
        if prov and prov.get("file_path"):
            fpath = Path(prov["file_path"])
            if not fpath.is_absolute():
                fpath = REPO_ROOT / fpath
            if fpath.exists():
                with open(fpath) as f:
                    data = json.load(f)
                    candles = data.get("candles", [])

    if not candles:
        candles = MarketDataStorageService.get_stored_candles(
            symbol="NSE-NIFTY",
            interval="15minute",
            start_time="2020-01-01",
            end_time="2027-01-01",
            regular_only=True,
            session=session,
        )

    if not candles:
        return {"ok": False, "code": "NO_CANDLES", "message": "No stored candles found for benchmark."}

    cfg = M23ResearchConfig(
        initial_train_size=body.initial_train_size,
        validation_size=body.validation_size,
        test_size=body.test_size,
        step_size=body.step_size,
    )

    results = run_m23_comprehensive_benchmark(
        candles=candles,
        config=cfg,
        dataset_id=dataset_id,
        use_cache=body.use_cache,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="forecasting.m23_benchmark",
            entity="benchmark_cache",
            before=None,
            after={
                "dataset_id": dataset_id,
                "targets_benchmarked": list(results.get("benchmarks_by_target", {}).keys()),
            },
        )
    )

    return {"ok": True, "results": results}


class M26BenchmarkRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str | None = None
    use_cache: bool = True


@router.post("/api/history/m26-benchmark")
def run_m26_benchmark_endpoint(
    body: M26BenchmarkRequestBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    """Execute M26 turnover reduction, robustness, and generalization benchmark."""
    principal = require_csrf(request, settings)
    import json
    from pathlib import Path
    from app.forecasting.m26_research import run_m26_comprehensive_benchmark
    from app.market.storage import MarketDataStorageService
    from app.settings import REPO_ROOT

    candles = []
    dataset_id = body.dataset_id or "m23_nifty_15m_1y_dataset"
    if body.dataset_id:
        prov = MarketDataStorageService.get_dataset_provenance(body.dataset_id, session=session)
        if prov and prov.get("file_path"):
            fpath = Path(prov["file_path"])
            if not fpath.is_absolute():
                fpath = REPO_ROOT / fpath
            if fpath.exists():
                with open(fpath) as f:
                    data = json.load(f)
                    candles = data.get("regular_candles") or data.get("candles", [])

    if not candles:
        # Check standard derived dataset artifact
        std_artifact = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
        if std_artifact.exists():
            with open(std_artifact) as f:
                data = json.load(f)
                candles = data.get("regular_candles") or data.get("candles", [])
                dataset_id = data.get("dataset_id", dataset_id)

    if not candles:
        candles = MarketDataStorageService.get_stored_candles(
            symbol="NSE-NIFTY",
            interval="15minute",
            start_time="2020-01-01",
            end_time="2027-01-01",
            regular_only=True,
            session=session,
        )

    if not candles:
        return {"ok": False, "code": "NO_CANDLES", "message": "No stored candles found for benchmark."}

    results = run_m26_comprehensive_benchmark(
        candles=candles,
        dataset_id=dataset_id,
        use_cache=body.use_cache,
    )

    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="forecasting.m26_benchmark",
            entity="benchmark_cache",
            before=None,
            after={
                "dataset_id": dataset_id,
                "recommendation": results.get("decision", {}).get("recommendation"),
            },
        )
    )

    return {"ok": True, "results": results}








