"""Create the shared persistence schema without changing runtime stores.

Revision ID: 0001_shared_persistence
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0001_shared_persistence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sequence_type = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    payload_type = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")

    op.create_table(
        "audit_events",
        sa.Column("sequence", sequence_type, primary_key=True, autoincrement=True),
        sa.Column("event_json", payload_type, nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )

    op.create_table(
        "audit_idempotency",
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("evidence_json", payload_type, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("claim_token", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("claimed_at", sa.Double(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("run_id", "event_type", name="pk_audit_idempotency"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.create_index(
        "ix_audit_idempotency_status_claimed_at",
        "audit_idempotency",
        ["status", "claimed_at"],
    )

    op.create_table(
        "action_plans",
        sa.Column("action_id", sa.String(length=255), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("payload", payload_type, nullable=False),
        sa.Column("created_order", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.create_index(
        "ix_action_plans_tenant_created_order",
        "action_plans",
        ["tenant_id", "created_order"],
    )

    op.create_table(
        "gitops_change_sets",
        sa.Column("change_id", sa.String(length=255), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("payload", payload_type, nullable=False),
        sa.Column("created_order", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    op.create_index(
        "ix_gitops_change_sets_tenant_created_order",
        "gitops_change_sets",
        ["tenant_id", "created_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_gitops_change_sets_tenant_created_order", table_name="gitops_change_sets")
    op.drop_table("gitops_change_sets")
    op.drop_index("ix_action_plans_tenant_created_order", table_name="action_plans")
    op.drop_table("action_plans")
    op.drop_index("ix_audit_idempotency_status_claimed_at", table_name="audit_idempotency")
    op.drop_table("audit_idempotency")
    op.drop_table("audit_events")
