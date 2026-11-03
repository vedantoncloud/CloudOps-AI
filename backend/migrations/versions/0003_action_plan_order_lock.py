"""Add a transactional action-plan creation-order allocator.

Revision ID: 0003_action_plan_order_lock
Revises: 0002_audit_chain_head_lock
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0003_action_plan_order_lock"
down_revision = "0002_audit_chain_head_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    singleton_type = sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql")
    op.create_table(
        "action_plan_state",
        sa.Column("singleton_id", singleton_type, primary_key=True),
        sa.Column("last_created_order", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    # Preserve the existing order when adopting a populated shared table.
    op.execute(
        """
        INSERT INTO action_plan_state (singleton_id, last_created_order)
        SELECT 1, COALESCE(MAX(created_order), 0)
        FROM action_plans
        """
    )


def downgrade() -> None:
    op.drop_table("action_plan_state")
