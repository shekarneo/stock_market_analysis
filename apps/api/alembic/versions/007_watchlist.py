"""Watchlist of desk suggestions with spot-based outcome tracking."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007_watchlist"
down_revision = "006_worker_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_suggestions",
        sa.Column("suggestion_id", sa.String(length=64), primary_key=True),
        sa.Column("instrument", sa.String(length=32), nullable=False),
        sa.Column("contract", sa.String(length=64), nullable=False),
        sa.Column("option_type", sa.String(length=4), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("call", sa.String(length=80), nullable=True),
        sa.Column("entry_spot", sa.Numeric(20, 4), nullable=False),
        sa.Column("target_spot", sa.Numeric(20, 4), nullable=False),
        sa.Column("stop_loss_spot", sa.Numeric(20, 4), nullable=False),
        sa.Column("model_premiums", postgresql.JSONB(), nullable=False),
        sa.Column("data_class", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_spot", sa.Numeric(20, 4), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_favorable_spot", sa.Numeric(20, 4), nullable=True),
        sa.Column("max_adverse_spot", sa.Numeric(20, 4), nullable=True),
        sa.Column("checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_spot", sa.Numeric(20, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction IN ('UP', 'DOWN')", name="watchlist_direction"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'TARGET_HIT', 'SL_HIT', 'AMBIGUOUS', 'EXPIRED', 'CANCELLED')",
            name="watchlist_status",
        ),
    )
    op.create_index("ix_watchlist_status", "watchlist_suggestions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_status", table_name="watchlist_suggestions")
    op.drop_table("watchlist_suggestions")
