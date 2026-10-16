"""Immutable paper-accounting journal. It does not change the risk ledger."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_paper_account_events"
down_revision = "003_risk_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_account_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intent_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("opening_cash_inr", sa.Numeric(20, 4), nullable=True),
        sa.Column("quantity", sa.Numeric(20, 4), nullable=True),
        sa.Column("price", sa.Numeric(20, 4), nullable=True),
        sa.Column("charges_inr", sa.Numeric(20, 4), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("effect", postgresql.JSONB(), nullable=False),
        sa.Column("ledger_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("broker_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ledger_applied = false", name="paper_account_events_not_applied"),
        sa.CheckConstraint("broker_confirmed = false", name="paper_account_events_not_broker_confirmed"),
        sa.CheckConstraint(
            "event_type IN ('FILL', 'PARTIAL_FILL', 'CANCEL', 'REJECT', 'CHARGE_ASSESSMENT', 'CHARGE_CORRECTION', 'RECONCILIATION_DISCREPANCY')",
            name="paper_account_events_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("paper_account_events")
