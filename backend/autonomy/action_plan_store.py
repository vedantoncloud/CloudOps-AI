"""Local durable storage for action plans and their latest lifecycle state."""

import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "action_plans.db"


class ActionPlanStore:
    """Persist plans in a dedicated SQLite file, separate from audit stores."""

    def __init__(self, database_path: str | Path | None = None):
        configured_path = database_path or os.getenv("CLOUDOPS_ACTION_PLANS_DB_PATH")
        self.database_path = Path(configured_path or DEFAULT_DB_PATH)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS action_plans (
                    action_id TEXT PRIMARY KEY,
                    tenant_id TEXT,
                    payload TEXT NOT NULL,
                    created_order INTEGER NOT NULL
                )"""
            )

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _encode(plan: ActionPlan) -> str:
        return json.dumps({
            "action_type": plan.action_type,
            "target": {
                "resource_type": plan.target.resource_type,
                "resource_id": plan.target.resource_id,
                "metadata": plan.target.metadata,
            },
            "reason": plan.reason,
            "risk": plan.risk.value,
            "requires_approval": plan.requires_approval,
            "rollback_available": plan.rollback_available,
            "status": plan.status.value,
            "decision_by": plan.decision_by,
            "decision_reason": plan.decision_reason,
            "action_id": plan.action_id,
        }, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode(payload: str) -> ActionPlan:
        value = json.loads(payload)
        return ActionPlan(
            action_type=value["action_type"],
            target=ActionTarget(**value["target"]),
            reason=value["reason"],
            risk=RiskLevel(value["risk"]),
            requires_approval=value["requires_approval"],
            rollback_available=value["rollback_available"],
            status=ActionStatus(value["status"]),
            decision_by=value["decision_by"],
            decision_reason=value["decision_reason"],
            action_id=value["action_id"],
        )

    def save_many(self, plans: Iterable[ActionPlan], tenant_id: str | None) -> None:
        with self._connect() as connection:
            for plan in plans:
                connection.execute(
                    """INSERT INTO action_plans(action_id, tenant_id, payload, created_order)
                       VALUES (?, ?, ?, COALESCE((SELECT MAX(created_order) + 1 FROM action_plans), 1))
                       ON CONFLICT(action_id) DO UPDATE SET
                         tenant_id=excluded.tenant_id, payload=excluded.payload""",
                    (plan.action_id, tenant_id, self._encode(plan)),
                )

    def get(self, action_id: str) -> tuple[ActionPlan, str | None] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, tenant_id FROM action_plans WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return (self._decode(row[0]), row[1]) if row else None

    def load_all(self) -> list[tuple[ActionPlan, str | None]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, tenant_id FROM action_plans ORDER BY created_order"
            ).fetchall()
        return [(self._decode(payload), tenant_id) for payload, tenant_id in rows]
