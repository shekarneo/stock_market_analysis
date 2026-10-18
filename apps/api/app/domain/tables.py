from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ConfigRevision(Base):
    __tablename__ = "config_revisions"

    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(128), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IntegrationCredential(Base):
    """Non-secret integration status. Secret values live only in ciphertext."""

    __tablename__ = "integration_credentials"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_expiry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    derived_access_token: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OperatorAccount(Base):
    """The one stored operator. The password is a salted hash, never the password."""

    __tablename__ = "operator_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OpsState(Base):
    __tablename__ = "ops_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class RiskSession(Base):
    """One local ledger row per session date. Null money means it was not configured."""

    __tablename__ = "risk_sessions"

    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    paper_cash_inr: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    reserved_inr: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    open_premium_at_risk_inr: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    lockout_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lockout_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    config_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    underlying: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expiry: Mapped[str | None] = mapped_column(String(10), nullable=True)
    strike: Mapped[str | None] = mapped_column(String(32), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(2), nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount_inr: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resulting_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaperTransition(Base):
    __tablename__ = "paper_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[str] = mapped_column(String(40), nullable=False)
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaperAccountEvent(Base):
    """Immutable research journal. A row is not a ledger fill and is not broker-confirmed."""

    __tablename__ = "paper_account_events"
    __table_args__ = (
        CheckConstraint("ledger_applied = false", name="paper_account_events_not_applied"),
        CheckConstraint("broker_confirmed = false", name="paper_account_events_not_broker_confirmed"),
        CheckConstraint(
            "event_type IN ('FILL', 'PARTIAL_FILL', 'CANCEL', 'REJECT', 'CHARGE_ASSESSMENT', 'CHARGE_CORRECTION', 'RECONCILIATION_DISCREPANCY')",
            name="paper_account_events_type",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    opening_cash_inr: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    charges_inr: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effect: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ledger_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    broker_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerLease(Base):
    """PostgreSQL row lease for worker process leadership and intent submission."""

    __tablename__ = "worker_leases"

    lease_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class WatchlistSuggestion(Base):
    """A desk suggestion saved for outcome tracking.

    The outcome is judged on the underlying spot (target_spot / stop_loss_spot), which is an
    observed Groww print. The option premiums are model estimates and are stored for reference
    only; they are never used to decide TARGET_HIT or SL_HIT.
    """

    __tablename__ = "watchlist_suggestions"
    __table_args__ = (
        CheckConstraint("direction IN ('UP', 'DOWN')", name="watchlist_direction"),
        CheckConstraint(
            "status IN ('OPEN', 'TARGET_HIT', 'SL_HIT', 'AMBIGUOUS', 'EXPIRED', 'CANCELLED')",
            name="watchlist_status",
        ),
    )

    suggestion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    contract: Mapped[str] = mapped_column(String(64), nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    call: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entry_spot: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    target_spot: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stop_loss_spot: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    model_premiums: Mapped[dict] = mapped_column(JSONB, nullable=False)
    data_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_spot: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_favorable_spot: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    max_adverse_spot: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_spot: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawResponseArtifact(Base):
    __tablename__ = "raw_response_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    candle_interval: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    candle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "timestamp", name="uq_market_candles_symbol_interval_ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    session_type: Mapped[str] = mapped_column(String(32), nullable=False, default="REGULAR")
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandleConflictAudit(Base):
    __tablename__ = "candle_conflict_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    existing_ohlcv: Mapped[dict] = mapped_column(JSONB, nullable=False)
    incoming_ohlcv: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resolution: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    incoming_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_ranges: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    completed_ranges: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    candles_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicts_detected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DatasetProvenanceRecord(Base):
    __tablename__ = "dataset_provenance"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_artifact_hashes: Mapped[list] = mapped_column(JSONB, nullable=False)
    verification_level: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BenchmarkCacheRecord(Base):
    __tablename__ = "benchmark_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    eval_settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    invalidated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

