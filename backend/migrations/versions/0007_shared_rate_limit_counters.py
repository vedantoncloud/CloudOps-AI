"""Add shared request rate-limit counters.

Revision ID: 0007_shared_rate_limit_counters
Revises: 0006_audit_tenant_scope
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_shared_rate_limit_counters"
down_revision = "0006_audit_tenant_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("bucket_key", sa.String(length=64), primary_key=True),
        sa.Column("window_number", sa.BigInteger(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.create_index("ix_rate_limit_counters_window_number", "rate_limit_counters", ["window_number"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_counters_window_number", table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
