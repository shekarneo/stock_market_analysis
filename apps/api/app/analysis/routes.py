"""Authenticated analysis request. The body cannot carry credentials or a provider URL."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.analysis.inference import commentary
from app.analysis.service import assemble_analysis
from app.market.live_quotes import stored_observations
from app.news.ingest import stored_news_observations
from app.auth import require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent, IntegrationCredential
from app.integrations.crypto import SecretBoxError, decrypt_secrets
from app.integrations.http import HttpxCaller
from app.settings import Settings, get_settings

router = APIRouter()


class AnalysisBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruments: list[str] = Field(min_length=1, max_length=32)
    horizon: Literal["INTRADAY", "SHORT_TERM", "LONGER_TERM"] = "INTRADAY"
    include_news: bool = True
    include_macro: bool = True
    include_derivatives: bool = True
    include_inference: bool = False
    include_forecast: bool = False
    enable_agent_llm: bool | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)


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


def _inference(session: Session, settings: Settings) -> dict:
    row = session.get(IntegrationCredential, "openai")
    if row is None or not row.ciphertext:
        return {"status": "NOT_CONFIGURED", "interpretations": [], "message": "OpenAI credentials are not saved."}
    if not row.enabled:
        return {"status": "INTEGRATION_DISABLED", "interpretations": [], "message": "OpenAI is disabled. No completion was sent."}
    try:
        secrets = decrypt_secrets(settings, row.ciphertext)
    except SecretBoxError as exc:
        return {"status": exc.code, "interpretations": [], "message": exc.message}
    api_key = secrets.get("api_key") or ""
    if not api_key or not row.model:
        return {"status": "NOT_CONFIGURED", "interpretations": [], "message": "OpenAI needs an API key and a model."}
    return {"status": "READY", "api_key": api_key, "model": row.model}


@router.post("/api/market-analysis")
def create_analysis(
    body: AnalysisBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> JSONResponse:
    principal = require_csrf(request, settings)

    def inference_factory(report: dict) -> dict:
        prepared = _inference(session, settings)
        public = {key: value for key, value in prepared.items() if key != "api_key"}
        public["requested"] = True
        public["attempted"] = False
        public["produced"] = False
        public.setdefault("interpretations", [])
        if prepared.get("status") != "READY":
            return public
        return commentary(HttpxCaller(), api_key=prepared["api_key"], model=prepared["model"], evidence=report.get("evidence") or [])

    observations = [*stored_observations(), *stored_news_observations()]
    report = assemble_analysis(
        instruments=body.instruments,
        horizon=body.horizon,
        include_news=body.include_news,
        include_macro=body.include_macro,
        include_derivatives=body.include_derivatives,
        include_inference=body.include_inference,
        include_forecast=body.include_forecast,
        enable_agent_llm=body.enable_agent_llm,
        observations=observations,
        idempotency_key=body.idempotency_key,
        inference_factory=inference_factory,
    )
    if report.get("status") != "FAILED" and "NIFTY" in body.instruments:
        # Every agent's call goes on the forward scorecard; recording never fails the analysis
        try:
            from app.analysis.agent_scorecard import latest_spot, record_agent_calls

            record_agent_calls(report, spot=latest_spot(observations))
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("imm.agent_scorecard").warning("Could not record agent calls: %s", exc)
    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="analysis.run",
            entity=report.get("analysis_id") or body.horizon,
            before=None,
            after={"status": report.get("status"), "decision": report.get("decision")},
        )
    )
    status = 200 if report.get("status") != "FAILED" else 422
    return JSONResponse(status_code=status, content=report)


@router.get("/api/analysis/agents/config")
def get_agents_config(request: Request, settings: Settings = Depends(_settings)) -> dict:
    from app.auth import read_session
    from app.analysis.agent_config import load_agent_system_config
    read_session(request, settings)
    return load_agent_system_config().model_dump()


@router.put("/api/analysis/agents/config")
@router.post("/api/analysis/agents/config")
def put_agents_config(
    request: Request,
    body: dict,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    import os
    principal = require_csrf(request, settings)
    from app.analysis.agent_config import MultiAgentSystemConfig, save_agent_system_config
    config = MultiAgentSystemConfig(**body)
    saved = save_agent_system_config(config)
    os.environ["IMM_ENABLE_AGENT_LLM"] = "1" if saved.enable_live_llm else "0"
    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="agents.config.update",
            entity="multi_agent_system",
            before=None,
            after={
                "version": saved.version,
                "agent_count": len(saved.agents),
                "enable_live_llm": saved.enable_live_llm,
                "auto_reroute_available_models": saved.auto_reroute_available_models,
            },
        )
    )
    return saved.model_dump()


@router.post("/api/analysis/agents/check-models")
def post_check_callable_models(
    request: Request,
    body: dict | None = None,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    from app.analysis.agent_config import load_agent_system_config, save_agent_system_config
    from app.analysis.ai_providers import AIProviderRegistry

    payload = body or {}
    auto_apply = bool(payload.get("auto_apply", False))
    probe = AIProviderRegistry.probe_callable_models()

    cfg = load_agent_system_config()
    if auto_apply and probe.get("best_callable"):
        best = probe["best_callable"]
        sec = probe.get("secondary_callable") or best
        callable_set = {(m["provider"], m["model"]) for m in probe.get("callable_models", [])}
        cfg.auto_reroute_available_models = True
        cfg.enable_live_llm = True
        for role, agent in cfg.agents.items():
            norm_p = "gemini" if agent.provider in {"google", "gemini"} else agent.provider
            if (norm_p, agent.model) not in callable_set:
                agent.provider = best["provider"]
                agent.model = best["model"]
            norm_fb = "gemini" if (agent.fallback_provider or "") in {"google", "gemini"} else (agent.fallback_provider or "")
            if not agent.fallback_provider or not agent.fallback_model or (norm_fb, agent.fallback_model) not in callable_set:
                agent.fallback_provider = sec["provider"]
                agent.fallback_model = sec["model"]
            agent.auto_reroute = True
        cfg = save_agent_system_config(cfg)
        session.add(
            AuditEvent(
                actor=principal.get("sub", "operator"),
                action="agents.config.auto_assign_callable_models",
                entity="multi_agent_system",
                before=None,
                after={
                    "best_callable": best,
                    "secondary_callable": sec,
                    "callable_count": len(probe.get("callable_models", [])),
                },
            )
        )

    return {
        "probe": probe,
        "config": cfg.model_dump(),
        "auto_applied": bool(auto_apply and probe.get("best_callable")),
    }


@router.post("/api/analysis/agents/reset")
def post_agents_reset(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    from app.analysis.agent_config import DEFAULT_AGENTS_CONFIG, MultiAgentSystemConfig, SingleAgentConfig, save_agent_system_config
    agents = {
        role: SingleAgentConfig(**cfg) for role, cfg in DEFAULT_AGENTS_CONFIG.items()
    }
    cfg = MultiAgentSystemConfig(version="v6.18.0", agents=agents)
    saved = save_agent_system_config(cfg)
    session.add(
        AuditEvent(
            actor=principal.get("sub", "operator"),
            action="agents.config.reset",
            entity="multi_agent_system",
            before=None,
            after={"version": saved.version},
        )
    )
    return saved.model_dump()


@router.get("/api/analysis/forecast-accuracy")
def get_forecast_accuracy(
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    from app.auth import read_session
    read_session(request, settings)
    from app.analysis.outcome_tracker import compute_forecast_accuracy_summary, get_forecast_records
    records = get_forecast_records()
    summary = compute_forecast_accuracy_summary(records)
    summary["forecasts"] = records[-50:]  # Latest 50 records
    return summary


@router.post("/api/analysis/forecast-accuracy/evaluate")
def post_evaluate_forecasts(
    request: Request,
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    from app.analysis.outcome_tracker import compute_forecast_accuracy_summary, evaluate_pending_forecasts
    from app.market.live_quotes import stored_observations
    obs = stored_observations()
    eval_res = evaluate_pending_forecasts(obs, min_elapsed_seconds=0)
    summary = compute_forecast_accuracy_summary()
    summary["evaluation_result"] = eval_res
    return summary
