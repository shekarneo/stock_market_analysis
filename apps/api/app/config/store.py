from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.loader import load_defaults, parse_document
from app.config.schemas import AppConfig, DataSource, OperatingMode, SECTION_MODELS
from app.db_locks import lock_operational
from app.domain.tables import AuditEvent, ConfigRevision, OpsState
from app.errors import ConfigValidationError, ModeForbidden
from app.security.redact import redact_value
from app.security.ssrf import guard_endpoint
from app.settings import Settings


def _secrets(settings: Settings) -> list[str]:
    return [settings.session_secret, settings.operator_password]


def ensure_seed(session: Session, settings: Settings) -> ConfigRevision:
    lock_operational(session)
    current = session.get(ConfigRevision, 1)
    if current is None:
        document = load_defaults(settings.defaults_path)
        current = ConfigRevision(
            revision=1,
            document=document.model_dump(mode="json"),
            actor="system",
        )
        session.add(current)
        session.add(
            AuditEvent(
                actor="system",
                action="config.seed",
                entity="config_revision:1",
                before=None,
                after=redact_value(document.model_dump(mode="json"), _secrets(settings)),
            )
        )
    if session.get(OpsState, 1) is None:
        session.add(OpsState(id=1, kill_switch=False, note=""))
    session.flush()
    return current


def latest(session: Session) -> ConfigRevision:
    row = session.scalar(select(ConfigRevision).order_by(ConfigRevision.revision.desc()).limit(1))
    if row is None:
        raise ConfigValidationError("configuration has not been seeded")
    return row


def current_config(session: Session) -> AppConfig:
    return parse_document(latest(session).document)


def _guard_runtime(runtime_mode: OperatingMode, live_trading_enabled: bool, settings: Settings, confirm_live: str | None) -> None:
    if runtime_mode is OperatingMode.LIVE_READ_ONLY:
        raise ModeForbidden(
            "LIVE_READ_ONLY stays unavailable until an authenticated read-only connection test exists."
        )
    if runtime_mode is OperatingMode.LIVE_TRADING or live_trading_enabled:
        if not settings.live_order_server_flag:
            raise ModeForbidden("The server live-order flag is off.")
        if confirm_live != "ENABLE LIVE TRADING":
            raise ModeForbidden("Live trading requires an explicit confirmation.")


def write_document(
    session: Session,
    settings: Settings,
    document: AppConfig,
    actor: str,
    confirm_live: str | None = None,
) -> ConfigRevision:
    _guard_runtime(document.runtime.mode, document.runtime.live_trading_enabled, settings, confirm_live)
    for source in document.sources:
        guard_endpoint(source.connector.value, source.endpoint)
    previous = latest(session)
    revision = ConfigRevision(
        revision=previous.revision + 1,
        document=document.model_dump(mode="json"),
        actor=actor,
    )
    session.add(revision)
    session.add(
        AuditEvent(
            actor=actor,
            action="config.write",
            entity=f"config_revision:{revision.revision}",
            before=redact_value(previous.document, _secrets(settings)),
            after=redact_value(revision.document, _secrets(settings)),
        )
    )
    session.flush()
    return revision


def replace_section(
    session: Session,
    settings: Settings,
    section: str,
    payload: dict,
    actor: str,
    confirm_live: str | None = None,
) -> ConfigRevision:
    if section not in SECTION_MODELS:
        raise ConfigValidationError(f"Unknown config section '{section}'.")
    model = SECTION_MODELS[section]
    try:
        parsed = model.model_validate(payload)
    except Exception as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            raise ConfigValidationError(exc.json()) from exc
        raise
    document = current_config(session).model_dump(mode="json")
    document[section] = parsed.model_dump(mode="json")
    return write_document(session, settings, parse_document(document), actor, confirm_live)


def upsert_source(
    session: Session,
    settings: Settings,
    source: DataSource,
    actor: str,
) -> ConfigRevision:
    guard_endpoint(source.connector.value, source.endpoint)
    document = current_config(session)
    sources = [item for item in document.sources if item.id != source.id]
    sources.append(source)
    updated = document.model_copy(update={"sources": sources})
    return write_document(session, settings, updated, actor)
