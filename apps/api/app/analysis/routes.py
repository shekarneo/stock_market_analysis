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

    report = assemble_analysis(
        instruments=body.instruments,
        horizon=body.horizon,
        include_news=body.include_news,
        include_macro=body.include_macro,
        include_derivatives=body.include_derivatives,
        include_inference=body.include_inference,
        include_forecast=body.include_forecast,
        observations=[*stored_observations(), *stored_news_observations()],
        idempotency_key=body.idempotency_key,
        inference_factory=inference_factory,
    )
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
