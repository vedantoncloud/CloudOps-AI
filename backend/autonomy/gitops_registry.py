import copy
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock

from autonomy.audit import AuditTrail
from autonomy.gitops import (
    GitOpsApplyResult,
    GitOpsChange,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)


class GitOpsChangeSetRegistry:
    """Thread-safe registry for governed GitOps changes with optional durability."""

    def __init__(
        self,
        audit_trail: AuditTrail | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        self.audit_trail = audit_trail if audit_trail is not None else AuditTrail()
        self._changes: dict[str, GitOpsChangeSet] = {}
        self._lock = RLock()
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
            # Invalid persisted state fails startup so pending reviews cannot disappear.
            self._changes = {
                change_set.change_id: change_set
                for (payload,) in rows
                for change_set in [self._decode(payload)]
            }

    def _connect(self):
        if self.database_path is None:
            raise RuntimeError("GitOps persistence is not configured")
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _encode(change_set: GitOpsChangeSet) -> str:
        return json.dumps(change_set.to_manifest(), separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode(payload: str) -> GitOpsChangeSet:
        value = json.loads(payload)
        return GitOpsChangeSet(
            change_id=value["change_id"],
            source_action_id=value["source_action_id"],
            changes=[GitOpsChange(**change) for change in value["changes"]],
            status=GitOpsChangeStatus(value["status"]),
            requires_approval=value["requires_approval"],
            approved_by=value.get("approved_by"),
            commit_message=value.get("commit_message", ""),
            metadata=value.get("metadata", {}),
        )

    def _persist_change(
        self, change_set: GitOpsChangeSet, previous: GitOpsChangeSet | None = None
    ) -> None:
        """Restore live state if its durable write fails."""
        previous = previous or copy.deepcopy(change_set)
        try:
            self._persist(change_set)
        except Exception:
            change_set.__dict__.clear()
            change_set.__dict__.update(previous.__dict__)
            raise

    def _persist(self, change_set: GitOpsChangeSet) -> None:
        if self.database_path is None:
            return
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
            if change_set.change_id in self._changes:
                raise ValueError(
                    f"change set already registered: {change_set.change_id}"
                )

            self._persist_change(change_set)
            self._changes[change_set.change_id] = change_set

            self.audit_trail.record(
                action_id=change_set.source_action_id,
                action_type="gitops_change_registered",
                resource_type="gitops_change_set",
                resource_id=change_set.change_id,
                event="gitops_change_registered",
                old_status="none",
                new_status=change_set.status.value,
                details={
                    "change_count": change_set.change_count,
                    **({"tenant_id": change_set.metadata["tenant_id"]}
                       if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
                },
                actor_id=actor_id,
            )

        return change_set

    def get(self, change_id: str) -> GitOpsChangeSet | None:
        with self._lock:
            return self._changes.get(change_id)

    def require(self, change_id: str) -> GitOpsChangeSet:
        change_set = self.get(change_id)

        if change_set is None:
            raise KeyError(f"GitOps change set not found: {change_id}")

        return change_set

    def list_all(self) -> list[GitOpsChangeSet]:
        with self._lock:
            return list(self._changes.values())

    def list_pending(self) -> list[GitOpsChangeSet]:
        with self._lock:
            return [
                change_set
                for change_set in self._changes.values()
                if change_set.status
                == GitOpsChangeStatus.PENDING_APPROVAL
            ]

    def approve(
        self,
        change_id: str,
        approved_by: str,
        *,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
    ) -> GitOpsChangeSet:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        previous = copy.deepcopy(change_set)
        engine.approve(change_set, approved_by)
        self._persist_change(change_set, previous)

        self.audit_trail.record(
            action_id=change_set.source_action_id,
            action_type="gitops_change_approved",
            resource_type="gitops_change_set",
            resource_id=change_id,
            event="gitops_change_approved",
            old_status=old_status,
            new_status=change_set.status.value,
            details={
                "approved_by": approved_by,
                **({"tenant_id": change_set.metadata["tenant_id"]}
                   if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
            },
            actor_id=actor_id,
        )

        return change_set

    def reject(
        self,
        change_id: str,
        rejected_by: str,
        reason: str,
        *,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
    ) -> GitOpsChangeSet:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        previous = copy.deepcopy(change_set)
        engine.reject(change_set, rejected_by, reason)
        self._persist_change(change_set, previous)

        self.audit_trail.record(
            action_id=change_set.source_action_id,
            action_type="gitops_change_rejected",
            resource_type="gitops_change_set",
            resource_id=change_id,
            event="gitops_change_rejected",
            old_status=old_status,
            new_status=change_set.status.value,
            details={
                "rejected_by": rejected_by,
                "reason": reason,
                **({"tenant_id": change_set.metadata["tenant_id"]}
                   if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
            },
            actor_id=actor_id,
        )

        return change_set

    def apply(
        self,
        change_id: str,
        *,
        dry_run: bool = True,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
    ) -> GitOpsApplyResult:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        previous = copy.deepcopy(change_set)
        result = engine.apply(
            change_set,
            dry_run=dry_run,
        )
        self._persist_change(change_set, previous)

        event_name = (
            "gitops_change_applied"
            if result.success
            else "gitops_apply_failed"
        )

        self.audit_trail.record(
            action_id=change_set.source_action_id,
            action_type=event_name,
            resource_type="gitops_change_set",
            resource_id=change_id,
            event=event_name,
            old_status=old_status,
            new_status=change_set.status.value,
            details={
                "dry_run": dry_run,
                "success": result.success,
                "applied_changes": result.applied_changes,
                "message": result.message,
                **({"tenant_id": change_set.metadata["tenant_id"]}
                   if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
            },
            actor_id=actor_id,
        )

        return result

    def verify(
        self,
        change_id: str,
        *,
        observed_values: dict[str, object] | None = None,
        engine: GitOpsEngine | None = None,
        actor_id: str | None = None,
    ) -> bool:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        previous = copy.deepcopy(change_set)
        verified = engine.verify(
            change_set,
            observed_values=observed_values,
        )
        self._persist_change(change_set, previous)

        event_name = (
            "gitops_change_verified"
            if verified
            else "gitops_verification_failed"
        )

        self.audit_trail.record(
            action_id=change_set.source_action_id,
            action_type=event_name,
            resource_type="gitops_change_set",
            resource_id=change_id,
            event=event_name,
            old_status=old_status,
            new_status=change_set.status.value,
            details={
                "verified": verified,
                "observed_values_provided": observed_values is not None,
                **({"tenant_id": change_set.metadata["tenant_id"]}
                   if isinstance(change_set.metadata.get("tenant_id"), str) else {}),
            },
            actor_id=actor_id,
        )

        return verified

    def clear(self) -> None:
        with self._lock:
            if self.database_path is not None:
                with self._connect() as connection:
                    connection.execute("DELETE FROM gitops_change_sets")
            self._changes.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._changes)
