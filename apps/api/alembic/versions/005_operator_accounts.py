"""Stored operator account and profile. The password is kept as a salted hash."""

from alembic import op
import sqlalchemy as sa

revision = "005_operator_accounts"
down_revision = "004_paper_account_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("operator_accounts")
