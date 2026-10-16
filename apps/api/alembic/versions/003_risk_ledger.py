"""M9 local risk ledger and paper transition rows."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_risk_ledger"
down_revision = "002_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_sessions",
        sa.Column("session_date", sa.Date(), primary_key=True),
        sa.Column("paper_cash_inr", sa.Numeric(20, 4), nullable=True),
        sa.Column("reserved_inr", sa.Numeric(20, 4), nullable=False),
        sa.Column("open_premium_at_risk_inr", sa.Numeric(20, 4), nullable=False),
        sa.Column("lockout_active", sa.Boolean(), nullable=False),
        sa.Column("lockout_reason", sa.String(length=200), nullable=True),
        sa.Column("config_revision", sa.Integer(), nullable=True),
        sa.Column("local_open_positions", sa.Integer(), nullable=False),
    )
    op.create_table(
        "risk_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("intent_id", sa.String(length=64), nullable=True),
        sa.Column("underlying", sa.String(length=16), nullable=True),
        sa.Column("expiry", sa.String(length=10), nullable=True),
        sa.Column("strike", sa.String(length=32), nullable=True),
        sa.Column("option_type", sa.String(length=2), nullable=True),
        sa.Column("quantity", sa.String(length=32), nullable=True),
        sa.Column("amount_inr", sa.Numeric(20, 4), nullable=True),
        sa.Column("provenance", sa.String(length=32), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("resulting_state", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_transitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("intent_id", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=40), nullable=False),
        sa.Column("to_state", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("paper_transitions")
    op.drop_table("risk_events")
    op.drop_table("risk_sessions")
