"""Run one analysis. The public request cannot supply observations or URLs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.analysis.graph import get_graph
from app.analysis.schema import HORIZONS, INSTRUMENTS, AnalysisReport

_RUNS: dict[str, dict] = {}
_GUARD = threading.Lock()
_KEY_LOCKS: dict[str, threading.Lock] = {}


def clear_runs() -> None:
    _RUNS.clear()


def _lock_for(key: str) -> threading.Lock:
    with _GUARD:
        lock = _KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _KEY_LOCKS[key] = lock
        return lock


def run_analysis(
    *,
    instruments: list[str],
    horizon: str = "INTRADAY",
    include_news: bool = True,
    include_macro: bool = True,
    include_derivatives: bool = True,
    include_inference: bool = False,
    include_forecast: bool = False,
    enable_agent_llm: bool | None = None,
    observations: list[dict] | None = None,
    inference: dict | None = None,
    idempotency_key: str | None = None,
    created_at: datetime | None = None,
) -> dict:
    if idempotency_key and idempotency_key in _RUNS:
        return _RUNS[idempotency_key]
    unknown = [name for name in instruments if name not in INSTRUMENTS]
    if unknown or not instruments:
        return _failure("UNKNOWN_INSTRUMENT", "One or more instruments are outside the analysis list.")
    if horizon not in HORIZONS:
        return _failure("UNSUPPORTED_HORIZON", "The horizon is not INTRADAY, SHORT_TERM, or LONGER_TERM.")
    moment = created_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        return _failure("INVALID_TIMESTAMP", "created_at must be timezone-aware.")
    run_id = str(uuid4())
    state = {
        "run_id": run_id,
        "created_at": moment.astimezone(timezone.utc).isoformat(),
        "instruments": list(instruments),
        "horizon": horizon,
        "include_news": include_news,
        "include_macro": include_macro,
        "include_derivatives": include_derivatives,
        "include_inference": include_inference,
        "include_forecast": include_forecast,
        "enable_agent_llm": enable_agent_llm,
        "accepted": _jsonable(list(observations or [])),
        "inference": _jsonable(inference or {"status": "NOT_REQUESTED"}),
    }
    try:
        result = get_graph().invoke(state, config={"configurable": {"thread_id": run_id}})
    except Exception:
        return _failure("GRAPH_FAILED", "The analysis graph failed. No report was invented.")
    report = result.get("report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        return _failure("REPORT_FAILED", "The analysis report was not produced.")
    public = _public(report)
    if idempotency_key:
        _RUNS[idempotency_key] = public
    return public


def assemble_analysis(
    *,
    instruments: list[str],
    horizon: str = "INTRADAY",
    include_news: bool = True,
    include_macro: bool = True,
    include_derivatives: bool = True,
    include_inference: bool = False,
    include_forecast: bool = False,
    enable_agent_llm: bool | None = None,
    idempotency_key: str | None = None,
    created_at: datetime | None = None,
    observations: list[dict] | None = None,
    inference_factory: Callable[[dict], dict] | None = None,
) -> dict:
    """Run the graph once. A shared idempotency key makes the paid call happen once."""
    lock = _lock_for(idempotency_key) if idempotency_key else None
    if lock is not None:
        lock.acquire()
    try:
        if idempotency_key and idempotency_key in _RUNS:
            return _RUNS[idempotency_key]
        report = run_analysis(
            instruments=instruments,
            horizon=horizon,
            include_news=include_news,
            include_macro=include_macro,
            include_derivatives=include_derivatives,
            include_inference=include_inference,
            include_forecast=include_forecast,
            enable_agent_llm=enable_agent_llm,
            observations=observations,
            inference={"status": "NOT_REQUESTED", "requested": False, "attempted": False, "produced": False, "interpretations": []},
            created_at=created_at,
        )
        if report.get("status") == "FAILED":
            if include_inference:
                report = apply_inference(
                    report,
                    {
                        "status": "SKIPPED",
                        "requested": True,
                        "attempted": False,
                        "produced": False,
                        "interpretations": [],
                        "message": "Commentary was not sent because the analysis report failed.",
                    },
                )
            return report
        if not include_inference:
            report = apply_inference(
                report,
                {"status": "NOT_REQUESTED", "requested": False, "attempted": False, "produced": False, "interpretations": []},
            )
            if idempotency_key:
                _RUNS[idempotency_key] = report
            return report
        try:
            inference = inference_factory(report) if inference_factory else {
                "status": "SKIPPED",
                "requested": True,
                "attempted": False,
                "produced": False,
                "interpretations": [],
                "message": "No commentary caller was configured.",
            }
        except Exception as exc:
            inference = {
                "status": "PROVIDER_ERROR",
                "requested": True,
                "attempted": False,
                "produced": False,
                "interpretations": [],
                "message": exc.__class__.__name__,
            }
        public = apply_inference(report, inference)
        if idempotency_key:
            _RUNS[idempotency_key] = public
        return public
    finally:
        if lock is not None:
            lock.release()


def apply_inference(report: dict, inference: dict) -> dict:
    """Attach commentary without changing evidence, status, decision, or approval flags."""
    body = dict(report)
    safe = {key: value for key, value in inference.items() if key not in {"api_key", "content", "messages"}}
    safe.pop("decision", None)
    safe.pop("forecast_ready", None)
    safe.pop("paper_approved", None)
    safe.pop("live_approved", None)
    safe.pop("real_market_data_verified", None)
    body["inference"] = safe
    if safe.get("requested"):
        limits = list(body.get("limitations") or [])
        note = "Model commentary is an interpretation and is not a market observation."
        if note not in limits:
            limits.append(note)
        body["limitations"] = limits
    return _public(body)


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _public(report: dict) -> dict:
    body = dict(report)
    body["forecast_ready"] = False
    body["paper_approved"] = False
    body["live_approved"] = False
    body["real_market_data_verified"] = False
    body["live_trading_enabled"] = False
    body["live_broker_routing_enabled"] = False
    body["confidence"] = None
    body["decision"] = "NO_TRADE"
    try:
        return AnalysisReport.model_validate(body).model_dump()
    except ValidationError:
        return _failure("SCHEMA_MISMATCH", "The analysis report did not match its schema.")


def _failure(code: str, message: str) -> dict:
    return AnalysisReport(
        status="FAILED",
        code=code,
        message=message,
        inference={"status": "NOT_REQUESTED"},
        limitations=["No report was invented after the failure."],
    ).model_dump()
