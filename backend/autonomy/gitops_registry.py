from dataclasses import dataclass
from threading import RLock

from autonomy.audit import AuditTrail
from autonomy.gitops import (
    GitOpsApplyResult,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)


class GitOpsChangeSetRegistry:
    """Thread-safe in-process registry for governed GitOps changes."""

    def __init__(self, audit_trail: AuditTrail | None = None) -> None:
        self.audit_trail = audit_trail if audit_trail is not None else AuditTrail()
        self._changes: dict[str, GitOpsChangeSet] = {}
        self._lock = RLock()

    def register(self, change_set: GitOpsChangeSet) -> GitOpsChangeSet:
        if not change_set.change_id.strip():
            raise ValueError("change_id cannot be empty")

        with self._lock:
            if change_set.change_id in self._changes:
                raise ValueError(
                    f"change set already registered: {change_set.change_id}"
                )

            self._changes[change_set.change_id] = change_set

            self.audit_trail.record(
                action_id=change_set.source_action_id,
                action_type="gitops_change_registered",
                resource_type="gitops_change_set",
                resource_id=change_set.change_id,
                event="gitops_change_registered",
                old_status="none",
                new_status=change_set.status.value,
                details={"change_count": change_set.change_count},
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
    ) -> GitOpsChangeSet:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        engine.approve(change_set, approved_by)

        self.audit_trail.record(
            action_id=change_set.source_action_id,
            action_type="gitops_change_approved",
            resource_type="gitops_change_set",
            resource_id=change_id,
            event="gitops_change_approved",
            old_status=old_status,
            new_status=change_set.status.value,
            details={"approved_by": approved_by},
        )

        return change_set

    def reject(
        self,
        change_id: str,
        rejected_by: str,
        reason: str,
        *,
        engine: GitOpsEngine | None = None,
    ) -> GitOpsChangeSet:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        engine.reject(change_set, rejected_by, reason)

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
            },
        )

        return change_set

    def apply(
        self,
        change_id: str,
        *,
        dry_run: bool = True,
        engine: GitOpsEngine | None = None,
    ) -> GitOpsApplyResult:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        result = engine.apply(
            change_set,
            dry_run=dry_run,
        )

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
            },
        )

        return result

    def verify(
        self,
        change_id: str,
        *,
        observed_values: dict[str, object] | None = None,
        engine: GitOpsEngine | None = None,
    ) -> bool:
        change_set = self.require(change_id)

        if engine is None:
            engine = GitOpsEngine()

        old_status = change_set.status.value
        verified = engine.verify(
            change_set,
            observed_values=observed_values,
        )

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
            },
        )

        return verified

    def clear(self) -> None:
        with self._lock:
            self._changes.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._changes)
