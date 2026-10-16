"""M0 additions: encrypted API integration credentials."""

from alembic import op
import sqlalchemy as sa

revision = "002_integrations"
down_revision = "001_m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_credentials",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=True),
        sa.Column("auth_method", sa.String(length=32), nullable=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("token_expiry", sa.String(length=64), nullable=True),
        sa.Column("derived_access_token", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_code", sa.String(length=64), nullable=True),
        sa.Column("last_test_message", sa.String(length=300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integration_credentials")
