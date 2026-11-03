"""Add a transactional GitOps change-set order allocator.

Revision ID: 0004_gitops_order_lock
Revises: 0003_action_plan_order_lock
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0004_gitops_order_lock"
down_revision = "0003_action_plan_order_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    singleton_type = sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql")
    op.create_table(
        "gitops_state",
        sa.Column("singleton_id", singleton_type, primary_key=True),
        sa.Column("last_created_order", sa.BigInteger(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    # Keep the existing shared registry order when adopting populated rows.
    op.execute(
        """
        INSERT INTO gitops_state (singleton_id, last_created_order)
        SELECT 1, COALESCE(MAX(created_order), 0)
        FROM gitops_change_sets
        """
    )


def downgrade() -> None:
    op.drop_table("gitops_state")
