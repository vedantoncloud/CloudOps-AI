"""Durable action-plan storage with SQLite and opt-in shared SQL backends."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "action_plans.db"


class ActionPlanStore:
    """Persist plans while preserving tenant ownership and stable creation order.

    SQLite remains the default. An explicit database_url selects the shared
    Alembic schema and serializes all writers on the singleton order row.
    """

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        database_url: str | None = None,
    ):
        if database_url and database_path is not None:
            raise ValueError("pass either database_path or database_url, not both")
        self._engine: Engine | None = None
        if database_url:
            if not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
                raise ValueError("database_url must use mysql+pymysql or sqlite")
            self.database_path: str | Path = database_url
            self._engine = create_engine(
                database_url,
                pool_pre_ping=True,
                future=True,
            )
            self._validate_shared_schema()
            return

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

    def _validate_shared_schema(self) -> None:
        assert self._engine is not None
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT action_id, tenant_id, payload, created_order "
                        "FROM action_plans LIMIT 0"
                    )
                )
                state = connection.execute(
                    text(
                        "SELECT singleton_id, last_created_order "
                        "FROM action_plan_state WHERE singleton_id = 1"
                    )
                ).first()
                if state is None:
                    raise ValueError("shared action-plan order row is missing")
        except (SQLAlchemyError, ValueError) as exc:
            self._engine.dispose()
            self._engine = None
            raise ValueError(
                "Shared action-plan schema is not initialized; run Alembic migrations first"
            ) from exc

    @property
    def uses_shared_database(self) -> bool:
        return self._engine is not None

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
            "created_at": plan.created_at.isoformat(),
        }, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode(payload: str) -> ActionPlan:
        value = json.loads(payload)
        created_at = datetime.fromisoformat(value["created_at"]) if value.get("created_at") else None
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
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
            created_at=created_at,
        )

    def save_many(
        self,
        plans: Iterable[ActionPlan],
        tenant_id: str | None,
        *,
        audit_trail=None,
        audit_events: list[dict] | None = None,
        expected_status: ActionStatus | None = None,
    ) -> None:
        plans = list(plans)
        if self._engine is not None:
            self._save_many_shared(
                plans, tenant_id, audit_trail, audit_events or [], expected_status
            )
            return
        if audit_events:
            raise ValueError("atomic audit events require shared SQL action-plan storage")

        with self._connect() as connection:
            for plan in plans:
                connection.execute(
                    """INSERT INTO action_plans(action_id, tenant_id, payload, created_order)
                       VALUES (?, ?, ?, COALESCE((SELECT MAX(created_order) + 1 FROM action_plans), 1))
                       ON CONFLICT(action_id) DO UPDATE SET
                         tenant_id=excluded.tenant_id, payload=excluded.payload""",
                    (plan.action_id, tenant_id, self._encode(plan)),
                )

    def _save_many_shared(
        self,
        plans: list[ActionPlan],
        tenant_id: str | None,
        audit_trail,
        audit_events: list[dict],
        expected_status: ActionStatus | None,
    ) -> None:
        assert self._engine is not None
        dialect = self._engine.dialect.name
        if dialect == "mysql":
            with self._engine.begin() as connection:
                self._save_many_locked(
                    connection, plans, tenant_id, " FOR UPDATE", audit_trail, audit_events, expected_status
                )
            return
        if dialect == "sqlite":
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    self._save_many_locked(
                        connection, plans, tenant_id, "", audit_trail, audit_events, expected_status
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return
        raise ValueError(f"Unsupported shared action-plan dialect: {dialect}")

    def _save_many_locked(
        self,
        connection,
        plans,
        tenant_id,
        lock_clause: str,
        audit_trail,
        audit_events: list[dict],
        expected_status: ActionStatus | None,
    ) -> None:
        # Lock the allocator first so concurrent inserts and updates of the same
        # action_id cannot race while assigning a new creation order.
        state = connection.execute(
            text(
                "SELECT last_created_order FROM action_plan_state "
                "WHERE singleton_id = 1" + lock_clause
            )
        ).mappings().one()
        last_order = int(state["last_created_order"])

        for plan in plans:
            existing_order = connection.execute(
                text(
                    "SELECT payload, tenant_id, created_order FROM action_plans "
                    "WHERE action_id = :action_id" + lock_clause
                ),
                {"action_id": plan.action_id},
            ).first()
            payload = self._encode(plan)
            if existing_order is None:
                last_order += 1
                connection.execute(
                    text(
                        "INSERT INTO action_plans "
                        "(action_id, tenant_id, payload, created_order) "
                        "VALUES (:action_id, :tenant_id, :payload, :created_order)"
                    ),
                    {
                        "action_id": plan.action_id,
                        "tenant_id": tenant_id,
                        "payload": payload,
                        "created_order": last_order,
                    },
                )
            else:
                if expected_status is not None:
                    stored_plan = self._decode(existing_order[0])
                    if stored_plan.status != expected_status:
                        raise ValueError(
                            "Action plan was modified by another worker; reload and retry"
                        )
                    if existing_order[1] != tenant_id:
                        raise ValueError(
                            "Action plan tenant ownership changed; reload and retry"
                        )
                connection.execute(
                    text(
                        "UPDATE action_plans SET tenant_id = :tenant_id, payload = :payload "
                        "WHERE action_id = :action_id"
                    ),
                    {
                        "action_id": plan.action_id,
                        "tenant_id": tenant_id,
                        "payload": payload,
                    },
                )

        connection.execute(
            text(
                "UPDATE action_plan_state SET last_created_order = :last_order "
                "WHERE singleton_id = 1"
            ),
            {"last_order": last_order},
        )
        if audit_events:
            if audit_trail is None or not getattr(audit_trail, "uses_shared_database", False):
                raise ValueError(
                    "atomic action-plan audit requires a shared PersistentAuditTrail"
                )
            for audit_event in audit_events:
                audit_trail.record_with_connection(connection, **audit_event)

    def get(self, action_id: str) -> tuple[ActionPlan, str | None] | None:
        if self._engine is not None:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT payload, tenant_id FROM action_plans "
                        "WHERE action_id = :action_id"
                    ),
                    {"action_id": action_id},
                ).first()
            return (self._decode(row[0]), row[1]) if row else None

        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, tenant_id FROM action_plans WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return (self._decode(row[0]), row[1]) if row else None

    def load_all(
        self,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> list[tuple[ActionPlan, str | None]]:
        """Load plans, applying tenant ownership in SQL when the caller is scoped."""
        if self._engine is not None:
            statement = "SELECT payload, tenant_id FROM action_plans"
            parameters = {}
            if tenant_scoped:
                statement += " WHERE tenant_id = :tenant_id"
                parameters["tenant_id"] = tenant_id
            statement += " ORDER BY created_order"
            with self._engine.connect() as connection:
                rows = connection.execute(text(statement), parameters).all()
            return [(self._decode(payload), stored_tenant) for payload, stored_tenant in rows]

        with self._connect() as connection:
            if tenant_scoped:
                rows = connection.execute(
                    "SELECT payload, tenant_id FROM action_plans "
                    "WHERE tenant_id = ? ORDER BY created_order",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload, tenant_id FROM action_plans ORDER BY created_order"
                ).fetchall()
        return [(self._decode(payload), stored_tenant) for payload, stored_tenant in rows]

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
