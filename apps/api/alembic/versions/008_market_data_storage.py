"""Milestone M23 Preparation: Persistent Market Data Storage, Audit, and Benchmark Cache.

Revision ID: 008_market_data_storage
Revises: 007_watchlist
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008_market_data_storage"
down_revision = "007_watchlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Raw response artifacts (stores immutable raw provider payload records)
    op.create_table(
        "raw_response_artifacts",
        sa.Column("artifact_id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("candle_interval", sa.String(length=16), nullable=False),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_byte_count", sa.Integer(), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_raw_artifacts_query",
        "raw_response_artifacts",
        ["symbol", "candle_interval", "requested_start", "requested_end"],
    )

    # 2. Normalized market candles (unique on symbol, interval, timestamp)
    op.create_table(
        "market_candles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(20, 4), nullable=False),
        sa.Column("high", sa.Numeric(20, 4), nullable=False),
        sa.Column("low", sa.Numeric(20, 4), nullable=False),
        sa.Column("close", sa.Numeric(20, 4), nullable=False),
        sa.Column("volume", sa.Numeric(20, 4), nullable=True),
        sa.Column("open_interest", sa.Numeric(20, 4), nullable=True),
        sa.Column("session_type", sa.String(length=32), nullable=False, server_default="REGULAR"),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("raw_artifact_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "interval", "timestamp", name="uq_market_candles_symbol_interval_ts"),
    )
    op.create_index(
        "ix_market_candles_lookup",
        "market_candles",
        ["symbol", "interval", "timestamp"],
    )

    # 3. Candle conflict audit (tracks any conflicting values detected during ingestion)
    op.create_table(
        "candle_conflict_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("existing_ohlcv", postgresql.JSONB(), nullable=False),
        sa.Column("incoming_ohlcv", postgresql.JSONB(), nullable=False),
        sa.Column("resolution", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("incoming_artifact_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candle_conflict_ts",
        "candle_conflict_audit",
        ["symbol", "interval", "timestamp"],
    )

    # 4. Ingestion runs (tracks incremental, resumable ingestion operations)
    op.create_table(
        "ingestion_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_ranges", postgresql.JSONB(), nullable=False),
        sa.Column("completed_ranges", postgresql.JSONB(), nullable=False),
        sa.Column("candles_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflicts_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 5. Dataset provenance & data-quality checks
    op.create_table(
        "dataset_provenance",
        sa.Column("dataset_id", sa.String(length=64), primary_key=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=16), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False),
        sa.Column("quality_report", postgresql.JSONB(), nullable=False),
        sa.Column("source_artifact_hashes", postgresql.JSONB(), nullable=False),
        sa.Column("verification_level", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 6. Benchmark cache (caches evaluation results by dataset, model, features, and settings)
    op.create_table(
        "benchmark_cache",
        sa.Column("cache_key", sa.String(length=64), primary_key=True),
        sa.Column("dataset_id", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("feature_config", postgresql.JSONB(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("eval_settings", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("invalidated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_benchmark_cache_lookup",
        "benchmark_cache",
        ["dataset_id", "model_version", "target"],
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_cache_lookup", table_name="benchmark_cache")
    op.drop_table("benchmark_cache")
    op.drop_table("dataset_provenance")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_candle_conflict_ts", table_name="candle_conflict_audit")
    op.drop_table("candle_conflict_audit")
    op.drop_index("ix_market_candles_lookup", table_name="market_candles")
    op.drop_table("market_candles")
    op.drop_index("ix_raw_artifacts_query", table_name="raw_response_artifacts")
    op.drop_table("raw_response_artifacts")
