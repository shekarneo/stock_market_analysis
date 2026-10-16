"""PostgreSQL row lease for worker process leadership and intent submission."""

from alembic import op
import sqlalchemy as sa

revision = "006_worker_leases"
down_revision = "005_operator_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_leases",
        sa.Column("lease_key", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_leases")
