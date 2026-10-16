"""M0 config revisions, audit events, and ops state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_m0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "config_revisions",
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=128), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ops_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ops_state")
    op.drop_table("audit_events")
    op.drop_table("config_revisions")
