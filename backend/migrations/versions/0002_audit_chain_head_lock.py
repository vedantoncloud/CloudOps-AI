"""Add a singleton lock/head row for cross-worker audit-chain appends.

Revision ID: 0002_audit_chain_head_lock
Revises: 0001_shared_persistence
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0002_audit_chain_head_lock"
down_revision = "0001_shared_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    singleton_type = sa.SmallInteger().with_variant(mysql.TINYINT(unsigned=True), "mysql")
    op.create_table(
        "audit_chain_state",
        sa.Column("singleton_id", singleton_type, primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    # Seed the head from any rows already present in the shared audit table.
    op.execute(
        """
        INSERT INTO audit_chain_state (singleton_id, last_sequence, last_hash)
        SELECT
            1,
            COALESCE(MAX(sequence), 0),
            COALESCE(
                (SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1),
                ''
            )
        FROM audit_events
        """
    )


def downgrade() -> None:
    op.drop_table("audit_chain_state")
