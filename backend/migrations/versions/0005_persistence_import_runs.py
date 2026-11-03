"""Record atomic legacy persistence imports for deterministic retries.

Revision ID: 0005_persistence_import_runs
Revises: 0004_gitops_order_lock
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0005_persistence_import_runs"
down_revision = "0004_gitops_order_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    report_type = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")
    op.create_table(
        "persistence_import_runs",
        sa.Column("manifest_sha256", sa.String(length=64), primary_key=True),
        sa.Column("report_json", report_type, nullable=False),
        sa.Column("imported_at", sa.String(length=40), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


def downgrade() -> None:
    op.drop_table("persistence_import_runs")
