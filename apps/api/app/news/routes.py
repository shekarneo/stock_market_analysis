"""Signed-in read of stored headlines, and a confirmed fetch of the public feeds."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth import read_session, require_csrf
from app.db import get_session_factory
from app.domain.tables import AuditEvent
from app.errors import AppError
from app.news.ingest import (
    add_news_source,
    delete_news_source,
    http_get,
    load_news,
    load_news_sources,
    reset_news_sources,
    run_news_read,
    toggle_news_source,
)
from app.settings import Settings, get_settings

router = APIRouter()


class NewsReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


class AddSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8)
    enabled: bool = True


class UpdateSourceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    name: str | None = None
    url: str | None = None


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


@router.get("/api/news/sources")
def list_news_sources(request: Request, settings: Settings = Depends(_settings)) -> dict:
    read_session(request, settings)
    sources = load_news_sources()
    latest_read = load_news()
    feed_meta = {}
    if latest_read and isinstance(latest_read.get("feeds"), list):
        for f in latest_read["feeds"]:
            feed_meta[f.get("id")] = f
    enriched = []
    for s in sources:
        meta = feed_meta.get(s["id"]) or {}
        enriched.append({
            **s,
            "last_status": meta.get("status"),
            "last_count": meta.get("count"),
            "last_error": meta.get("error"),
        })
    return {
        "sources": enriched,
        "active_count": sum(1 for s in sources if s.get("enabled", True)),
        "total_count": len(sources),
    }


@router.post("/api/news/sources")
def add_source_endpoint(
    body: AddSourceBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        new_source = add_news_source(name=body.name, url=body.url, enabled=body.enabled)
    except ValueError as exc:
        raise AppError("INVALID_FEED", str(exc), 422)
    session.add(
        AuditEvent(
            actor=principal.get("username") or principal.get("sub") or "operator",
            action="news.source_add",
            entity=new_source["id"],
            before=None,
            after=new_source,
        )
    )
    return new_source


@router.patch("/api/news/sources/{source_id}")
def update_source_endpoint(
    source_id: str,
    body: UpdateSourceBody,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    try:
        updated = toggle_news_source(source_id, enabled=body.enabled)
    except KeyError:
        raise AppError("NOT_FOUND", f"News feed '{source_id}' not found.", 404)
    session.add(
        AuditEvent(
            actor=principal.get("username") or principal.get("sub") or "operator",
            action="news.source_toggle",
            entity=source_id,
            before=None,
            after=updated,
        )
    )
    return updated


@router.delete("/api/news/sources/{source_id}")
def delete_source_endpoint(
    source_id: str,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    removed = delete_news_source(source_id)
    if not removed:
        raise AppError("NOT_FOUND", f"News feed '{source_id}' not found.", 404)
    session.add(
        AuditEvent(
            actor=principal.get("username") or principal.get("sub") or "operator",
            action="news.source_delete",
            entity=source_id,
            before=None,
            after={"deleted": True},
        )
    )
    return {"deleted": True, "id": source_id}


@router.post("/api/news/sources/reset")
def reset_sources_endpoint(
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(_settings),
) -> dict:
    principal = require_csrf(request, settings)
    sources = reset_news_sources()
    session.add(
        AuditEvent(
            actor=principal.get("username") or principal.get("sub") or "operator",
            action="news.sources_reset",
            entity="sources",
            before=None,
            after={"count": len(sources)},
        )
    )
    return {"sources": sources, "reset": True}

