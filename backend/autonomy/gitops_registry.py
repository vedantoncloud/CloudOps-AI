from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from autonomy.audit import AuditTrail
from autonomy.gitops import (
    GitOpsApplyResult,
    GitOpsChange,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)


class GitOpsChangeSetRegistry:
    """Thread-safe GitOps registry with SQLite and opt-in shared SQL storage."""

    def __init__(
        self,
        audit_trail: AuditTrail | None = None,
        database_path: str | Path | None = None,
        *,
        database_url: str | None = None,
    ) -> None:
        if database_url and database_path is not None:
            raise ValueError("pass either database_path or database_url, not both")
        self.audit_trail = audit_trail if audit_trail is not None else AuditTrail()
        self._changes: dict[str, GitOpsChangeSet] = {}
        self._lock = RLock()
        self._engine: Engine | None = None

        if database_url:
            if not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
                raise ValueError("database_url must use mysql+pymysql or sqlite")
            self.database_path: str | Path | None = database_url
            self._engine = create_engine(
                database_url,
                pool_pre_ping=True,
                future=True,
            )
            self._validate_shared_schema()
            self._changes = {
                item.change_id: item for item in self._load_shared_all()
            }
            return

        configured_path = database_path or os.getenv("CLOUDOPS_GITOPS_DB_PATH")
        self.database_path = Path(configured_path) if configured_path else None
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS gitops_change_sets (
                        change_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        created_order INTEGER NOT NULL
                    )"""
                )
                rows = connection.execute(
                    "SELECT payload FROM gitops_change_sets ORDER BY created_order"
                ).fetchall()
            self._changes = {
                change_set.change_id: change_set
                for (payload,) in rows
                for change_set in [self._decode(payload)]
            }

    def _validate_shared_schema(self) -> None:
        assert self._engine is not None
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT change_id, tenant_id, payload, created_order "
                        "FROM gitops_change_sets LIMIT 0"
                    )
                )
                state = connection.execute(
                    text(
                        "SELECT singleton_id, last_created_order "
                        "FROM gitops_state WHERE singleton_id = 1"
                    )
                ).first()
                if state is None:
                    raise ValueError("shared GitOps order row is missing")
        except (SQLAlchemyError, ValueError) as exc:
            self._engine.dispose()
            self._engine = None
            raise ValueError(
                "Shared GitOps schema is not initialized; run Alembic migrations first"
            ) from exc

    def _connect(self):
        if self.database_path is None or self._engine is not None:
            raise RuntimeError("GitOps SQLite persistence is not configured")
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _encode(change_set: GitOpsChangeSet) -> str:
        return json.dumps(
            change_set.to_manifest(),
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _decode(payload: str, tenant_id: str | None = None) -> GitOpsChangeSet:
        value = json.loads(payload)
        metadata = value.get("metadata", {})
        if tenant_id is not None:
            if metadata.get("tenant_id") != tenant_id:
                raise ValueError("persisted GitOps tenant ownership metadata is inconsistent")
            metadata = {**metadata, "tenant_id": tenant_id}
        return GitOpsChangeSet(
            change_id=value["change_id"],
            source_action_id=value["source_action_id"],
            changes=[GitOpsChange(**change) for change in value["changes"]],
            status=GitOpsChangeStatus(value["status"]),
            requires_approval=value["requires_approval"],
            approved_by=value.get("approved_by"),
            commit_message=value.get("commit_message", ""),
            metadata=metadata,
        )

    @staticmethod
    def _tenant_id(change_set: GitOpsChangeSet) -> str | None:
        value = change_set.metadata.get("tenant_id")
        return value if isinstance(value, str) else None

    def _load_shared_one(
        self,
        change_id: str,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> GitOpsChangeSet | None:
        assert self._engine is not None
        statement = (
            "SELECT payload, tenant_id FROM gitops_change_sets "
            "WHERE change_id = :change_id"
        )
        parameters = {"change_id": change_id}
        if tenant_scoped:
            statement += " AND tenant_id = :tenant_id"
            parameters["tenant_id"] = tenant_id
        with self._engine.connect() as connection:
            row = connection.execute(text(statement), parameters).first()
        return self._decode(row[0], row[1]) if row else None

    def _load_shared_all(
        self,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> list[GitOpsChangeSet]:
        assert self._engine is not None
        statement = "SELECT payload, tenant_id FROM gitops_change_sets"
        parameters = {}
        if tenant_scoped:
            statement += " WHERE tenant_id = :tenant_id"
            parameters["tenant_id"] = tenant_id
        statement += " ORDER BY created_order"
        with self._engine.connect() as connection:
            rows = connection.execute(text(statement), parameters).all()
        return [self._decode(payload, stored_tenant) for payload, stored_tenant in rows]

    def _record_audit_on_connection(self, connection, audit_event: dict | None) -> bool:
        if not audit_event or not getattr(self.audit_trail, "uses_shared_database", False):
            return False
        self.audit_trail.record_with_connection(connection, **audit_event)
        return True

    def _persist_new_shared(
        self,
        change_set: GitOpsChangeSet,
        audit_event: dict | None = None,
    ) -> bool:
        assert self._engine is not None
        dialect = self._engine.dialect.name
        if dialect == "mysql":
            with self._engine.begin() as connection:
                return self._insert_shared_locked(
                    connection, change_set, " FOR UPDATE", audit_event
                )
        if dialect == "sqlite":
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    atomic_audit = self._insert_shared_locked(
                        connection, change_set, "", audit_event
                    )
                    connection.commit()
                    return atomic_audit
                except Exception:
                    connection.rollback()
                    raise
            return
        raise ValueError(f"Unsupported shared GitOps dialect: {dialect}")

    def _insert_shared_locked(
        self, connection, change_set, lock_clause: str, audit_event: dict | None
    ) -> bool:
        state = connection.execute(
            text(
                "SELECT last_created_order FROM gitops_state "
                "WHERE singleton_id = 1" + lock_clause
            )
        ).mappings().one()
        existing = connection.execute(
            text(
                "SELECT 1 FROM gitops_change_sets WHERE change_id = :change_id"
                + lock_clause
            ),
            {"change_id": change_set.change_id},
        ).first()
        if existing is not None:
            raise ValueError(f"change set already registered: {change_set.change_id}")

        next_order = int(state["last_created_order"]) + 1
        connection.execute(
            text(
                "INSERT INTO gitops_change_sets "
                "(change_id, tenant_id, payload, created_order) "
                "VALUES (:change_id, :tenant_id, :payload, :created_order)"
            ),
            {
                "change_id": change_set.change_id,
                "tenant_id": self._tenant_id(change_set),
                "payload": self._encode(change_set),
                "created_order": next_order,
            },
        )
        connection.execute(
            text(
                "UPDATE gitops_state SET last_created_order = :next_order "
                "WHERE singleton_id = 1"
            ),
            {"next_order": next_order},
        )
        return self._record_audit_on_connection(connection, audit_event)

    def _persist_shared_change(
        self,
        change_set: GitOpsChangeSet,
        previous: GitOpsChangeSet,
        audit_event: dict | None = None,
    ) -> bool:
        assert self._engine is not None
        dialect = self._engine.dialect.name
        if dialect == "mysql":
            with self._engine.begin() as connection:
                return self._update_shared_locked(
                    connection, change_set, previous, " FOR UPDATE", audit_event
                )
        if dialect == "sqlite":
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    atomic_audit = self._update_shared_locked(
                        connection, change_set, previous, "", audit_event
                    )
                    connection.commit()
                    return atomic_audit
                except Exception:
                    connection.rollback()
                    raise
            return
        raise ValueError(f"Unsupported shared GitOps dialect: {dialect}")

    def _update_shared_locked(
        self,
        connection,
        change_set: GitOpsChangeSet,
        previous: GitOpsChangeSet,
        lock_clause: str,
        audit_event: dict | None,
    ) -> bool:
        row = connection.execute(
            text(
                "SELECT payload, tenant_id FROM gitops_change_sets "
                "WHERE change_id = :change_id" + lock_clause
            ),
            {"change_id": change_set.change_id},
        ).first()
        if row is None:
            raise KeyError(f"GitOps change set not found: {change_set.change_id}")
        if row[0] != self._encode(previous) or row[1] != self._tenant_id(previous):
            raise ValueError(
                "GitOps change set was modified by another worker; reload and retry"
            )
        connection.execute(
            text(
                "UPDATE gitops_change_sets SET tenant_id = :tenant_id, payload = :payload "
                "WHERE change_id = :change_id"
            ),
            {
                "change_id": change_set.change_id,
                "tenant_id": self._tenant_id(change_set),
                "payload": self._encode(change_set),
            },
        )
        return self._record_audit_on_connection(connection, audit_event)

    def _persist_change(
        self,
        change_set: GitOpsChangeSet,
        previous: GitOpsChangeSet | None = None,
        audit_event: dict | None = None,
    ) -> bool:
        """Restore live state if its durable write fails."""
        previous = previous or copy.deepcopy(change_set)
        try:
            if self._engine is not None:
                return self._persist_shared_change(change_set, previous, audit_event)
            self._persist(change_set)
            return False
        except Exception:
            change_set.__dict__.clear()
            change_set.__dict__.update(previous.__dict__)
            if self._engine is not None:
                refreshed = self._load_shared_one(change_set.change_id)
                if refreshed is not None:
                    self._changes[change_set.change_id] = refreshed
                else:
                    self._changes.pop(change_set.change_id, None)
            raise

    def _persist(self, change_set: GitOpsChangeSet) -> None:
        if self.database_path is None:
            return
        if self._engine is not None:
            raise RuntimeError("shared GitOps writes require a transaction")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO gitops_change_sets(change_id, payload, created_order)
                   VALUES (?, ?, COALESCE((SELECT MAX(created_order) + 1
                                           FROM gitops_change_sets), 1))
                   ON CONFLICT(change_id) DO UPDATE SET payload=excluded.payload""",
                (change_set.change_id, self._encode(change_set)),
            )

    def register(
        self, change_set: GitOpsChangeSet, *, actor_id: str | None = None
    ) -> GitOpsChangeSet:
        if not change_set.change_id.strip():
            raise ValueError("change_id cannot be empty")

        with self._lock:
            if self._engine is None and change_set.change_id in self._changes:
                raise ValueError(
                    f"change set already registered: {change_set.change_id}"
                )
            audit_event = {
                "action_id": change_set.source_action_id,
                "action_type": "gitops_change_registered",
                "resource_type": "gitops_change_set",
                "resource_id": change_set.change_id,
                "event": "gitops_change_registered",
                "old_status": "none",
                "new_status": change_set.status.value,
                "details": {
                    "change_count": change_set.change_count,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                "actor_id": actor_id,
            }
            if self._engine is not None:
                atomic_audit = self._persist_new_shared(change_set, audit_event)
            else:
                self._persist_change(change_set)
                atomic_audit = False
            self._changes[change_set.change_id] = change_set
            if not atomic_audit:
                self.audit_trail.record(**audit_event)

        return change_set

    def get(
        self,
        change_id: str,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> GitOpsChangeSet | None:
        with self._lock:
            if self._engine is not None:
                change_set = self._load_shared_one(
                    change_id, tenant_id, tenant_scoped=tenant_scoped
                )
                if not tenant_scoped:
                    if change_set is None:
                        self._changes.pop(change_id, None)
                    else:
                        self._changes[change_id] = change_set
                return change_set
            change_set = self._changes.get(change_id)
            if (
                tenant_scoped
                and change_set is not None
                and change_set.metadata.get("tenant_id") != tenant_id
            ):
                return None
            return change_set

    def require(
        self,
        change_id: str,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> GitOpsChangeSet:
        change_set = self.get(
            change_id, tenant_id, tenant_scoped=tenant_scoped
        )
        if change_set is None:
            raise KeyError(f"GitOps change set not found: {change_id}")
        return change_set

    def _require_for_tenant(
        self,
        change_id: str,
        tenant_id: str | None,
        tenant_scoped: bool,
    ) -> GitOpsChangeSet:
        return self.require(
            change_id, tenant_id, tenant_scoped=tenant_scoped
        )

    def list_all(
        self,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> list[GitOpsChangeSet]:
        with self._lock:
            if self._engine is not None:
                changes = self._load_shared_all(
                    tenant_id, tenant_scoped=tenant_scoped
                )
                if not tenant_scoped:
                    self._changes = {item.change_id: item for item in changes}
                return changes
            changes = list(self._changes.values())
            if tenant_scoped:
                changes = [
                    item for item in changes
                    if item.metadata.get("tenant_id") == tenant_id
                ]
            return changes

    def list_pending(
        self,
        tenant_id: str | None = None,
        *,
        tenant_scoped: bool = False,
    ) -> list[GitOpsChangeSet]:
        return [
            change_set
            for change_set in self.list_all(
                tenant_id, tenant_scoped=tenant_scoped
            )
            if change_set.status == GitOpsChangeStatus.PENDING_APPROVAL
        ]

    def approve(
        self,
        change_id: str,
        approved_by: str,
        *,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        tenant_scoped: bool = False,
    ) -> GitOpsChangeSet:
        with self._lock:
            change_set = self._require_for_tenant(change_id, tenant_id, tenant_scoped)
            if engine is None:
                engine = GitOpsEngine()

            old_status = change_set.status.value
            previous = copy.deepcopy(change_set)
            engine.approve(change_set, approved_by)
            audit_event = {
                "action_id": change_set.source_action_id,
                "action_type": "gitops_change_approved",
                "resource_type": "gitops_change_set",
                "resource_id": change_id,
                "event": "gitops_change_approved",
                "old_status": old_status,
                "new_status": change_set.status.value,
                "details": {
                    "approved_by": approved_by,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                "actor_id": actor_id,
            }
            atomic_audit = self._persist_change(change_set, previous, audit_event)
            if not atomic_audit:
                self.audit_trail.record(**audit_event)
            return change_set

    def reject(
        self,
        change_id: str,
        rejected_by: str,
        reason: str,
        *,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        tenant_scoped: bool = False,
    ) -> GitOpsChangeSet:
        with self._lock:
            change_set = self._require_for_tenant(change_id, tenant_id, tenant_scoped)
            if engine is None:
                engine = GitOpsEngine()

            old_status = change_set.status.value
            previous = copy.deepcopy(change_set)
            engine.reject(change_set, rejected_by, reason)
            audit_event = {
                "action_id": change_set.source_action_id,
                "action_type": "gitops_change_rejected",
                "resource_type": "gitops_change_set",
                "resource_id": change_id,
                "event": "gitops_change_rejected",
                "old_status": old_status,
                "new_status": change_set.status.value,
                "details": {
                    "rejected_by": rejected_by,
                    "reason": reason,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                "actor_id": actor_id,
            }
            atomic_audit = self._persist_change(change_set, previous, audit_event)
            if not atomic_audit:
                self.audit_trail.record(**audit_event)
            return change_set

    def apply(
        self,
        change_id: str,
        *,
        dry_run: bool = True,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        tenant_scoped: bool = False,
    ) -> GitOpsApplyResult:
        with self._lock:
            change_set = self._require_for_tenant(change_id, tenant_id, tenant_scoped)
            if engine is None:
                engine = GitOpsEngine()

            old_status = change_set.status.value
            previous = copy.deepcopy(change_set)
            result = engine.apply(change_set, dry_run=dry_run)

            event_name = (
                "gitops_change_applied"
                if result.success
                else "gitops_apply_failed"
            )
            audit_event = {
                "action_id": change_set.source_action_id,
                "action_type": event_name,
                "resource_type": "gitops_change_set",
                "resource_id": change_id,
                "event": event_name,
                "old_status": old_status,
                "new_status": change_set.status.value,
                "details": {
                    "dry_run": dry_run,
                    "success": result.success,
                    "applied_changes": result.applied_changes,
                    "message": result.message,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                "actor_id": actor_id,
            }
            atomic_audit = self._persist_change(change_set, previous, audit_event)
            if not atomic_audit:
                self.audit_trail.record(**audit_event)
            return result

    def verify(
        self,
        change_id: str,
        *,
        observed_values: dict[str, object] | None = None,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        tenant_scoped: bool = False,
    ) -> bool:
        with self._lock:
            change_set = self._require_for_tenant(change_id, tenant_id, tenant_scoped)
            if engine is None:
                engine = GitOpsEngine()

            old_status = change_set.status.value
            previous = copy.deepcopy(change_set)
            verified = engine.verify(change_set, observed_values=observed_values)

            event_name = (
                "gitops_change_verified"
                if verified
                else "gitops_verification_failed"
            )
            audit_event = {
                "action_id": change_set.source_action_id,
                "action_type": event_name,
                "resource_type": "gitops_change_set",
                "resource_id": change_id,
                "event": event_name,
                "old_status": old_status,
                "new_status": change_set.status.value,
                "details": {
                    "verified": verified,
                    "observed_values_provided": observed_values is not None,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                "actor_id": actor_id,
            }
            atomic_audit = self._persist_change(change_set, previous, audit_event)
            if not atomic_audit:
                self.audit_trail.record(**audit_event)
            return verified

    def clear(self) -> None:
        with self._lock:
            if self._engine is not None:
                dialect = self._engine.dialect.name
                if dialect == "mysql":
                    with self._engine.begin() as connection:
                        connection.execute(
                            text(
                                "SELECT singleton_id FROM gitops_state "
                                "WHERE singleton_id = 1 FOR UPDATE"
                            )
                        ).one()
                        connection.execute(text("DELETE FROM gitops_change_sets"))
                        connection.execute(
                            text(
                                "UPDATE gitops_state SET last_created_order = 0 "
                                "WHERE singleton_id = 1"
                            )
                        )
                elif dialect == "sqlite":
                    with self._engine.connect() as connection:
                        connection.exec_driver_sql("BEGIN IMMEDIATE")
                        try:
                            connection.execute(text("DELETE FROM gitops_change_sets"))
                            connection.execute(
                                text(
                                    "UPDATE gitops_state SET last_created_order = 0 "
                                    "WHERE singleton_id = 1"
                                )
                            )
                            connection.commit()
                        except Exception:
                            connection.rollback()
                            raise
                else:
                    raise ValueError(f"Unsupported shared GitOps dialect: {dialect}")
            elif self.database_path is not None:
                with self._connect() as connection:
                    connection.execute("DELETE FROM gitops_change_sets")
            self._changes.clear()

    def __len__(self) -> int:
        if self._engine is not None:
            return len(self.list_all())
        with self._lock:
            return len(self._changes)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
