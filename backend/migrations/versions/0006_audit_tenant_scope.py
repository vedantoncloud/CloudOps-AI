
"""Add indexed tenant ownership to persistent audit events.

Revision ID: 0006_audit_tenant_scope
Revises: 0005_persistence_import_runs
"""

import json

from alembic import op
import sqlalchemy as sa

revision = "0006_audit_tenant_scope"
down_revision = "0005_persistence_import_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("tenant_id", sa.String(length=255), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT sequence, event_json FROM audit_events")
    ).mappings()
    for row in rows:
        try:
            event = json.loads(row["event_json"])
            details = event.get("details", {})
            tenant_id = details.get("tenant_id") if isinstance(details, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            tenant_id = None
        if isinstance(tenant_id, str):
            bind.execute(
                sa.text(
                    "UPDATE audit_events SET tenant_id = :tenant_id "
                    "WHERE sequence = :sequence"
                ),
                {"tenant_id": tenant_id, "sequence": row["sequence"]},
            )
    op.create_index(
        "ix_audit_events_tenant_sequence",
        "audit_events",
        ["tenant_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_sequence", table_name="audit_events")
    op.drop_column("audit_events", "tenant_id")
