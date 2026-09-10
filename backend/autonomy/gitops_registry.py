from dataclasses import dataclass
from threading import RLock

from autonomy.gitops import (
    GitOpsApplyResult,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)


class GitOpsChangeSetRegistry:
    """Thread-safe in-process registry for governed GitOps changes."""

    def __init__(self) -> None:
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

        engine.approve(change_set, approved_by)

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

        engine.reject(change_set, rejected_by, reason)

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

        return engine.apply(
            change_set,
            dry_run=dry_run,
        )

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

        return engine.verify(
            change_set,
            observed_values=observed_values,
        )

    def clear(self) -> None:
        with self._lock:
            self._changes.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._changes)
