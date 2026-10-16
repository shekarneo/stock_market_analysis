"""Signed-in read of stored headlines, and a confirmed fetch of the public feeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent
from app.news.ingest import http_get, load_news, run_news_read
from app.settings import Settings, get_settings

router = APIRouter()


class NewsReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


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


@router.get("/api/news")
def read_news(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    record = load_news()
    if record is None:
        return {
            "status": "NOT_READ",
            "retrieved_at": None,
            "network_calls": 0,
            "count": 0,
            "items": [],
            "feeds": [],
            "directional_implication": "UNKNOWN",
            "decision": "NO_TRADE",
        }
    items = [
        {
            "claim": row.get("claim"),
            "source_name": row.get("source_name"),
            "source_url": row.get("source_url"),
            "summary": row.get("summary") or "",
            "published_at": row.get("published_at"),
            "retrieved_at": row.get("retrieved_at"),
            "directional_implication": "UNKNOWN",
        }
        for row in record.get("items") or []
        if isinstance(row, dict)
    ]
    return {
        "status": record.get("status") or "READ",
        "retrieved_at": record.get("retrieved_at"),
        "network_calls": record.get("network_calls", 0),
        "count": len(items),
        "items": items,
        "feeds": record.get("feeds") or [],
        "directional_implication": "UNKNOWN",
        "decision": "NO_TRADE",
    }


@router.post("/api/news/refresh")
def refresh_news(
    body: NewsReadBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    del body
    result = run_news_read(getter=http_get, retrieved_at=datetime.now(timezone.utc))
    session.add(
        AuditEvent(
            actor=principal.get("username") or principal.get("sub") or "operator",
            action="news.refresh",
            entity="public_feeds",
            before=None,
            after={"status": result["status"], "count": result["count"]},
        )
    )
    return result
