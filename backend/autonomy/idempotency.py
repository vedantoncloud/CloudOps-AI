from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from autonomy.action_models import ActionPlan, ActionStatus


@dataclass(frozen=True)
class ExecutionRecord:
    action_id: str
    execution_id: str
    status: ActionStatus
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class IdempotencyManager:
    """Prevent duplicate execution attempts for the same action."""

    BLOCKED_STATUSES = frozenset({
        ActionStatus.EXECUTING,
        ActionStatus.VERIFYING,
        ActionStatus.SUCCEEDED,
        ActionStatus.ROLLBACK_REQUIRED,
        ActionStatus.ROLLED_BACK,
        ActionStatus.FAILED,
    })

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}
        self._lock = Lock()

    def start_execution(self, action: ActionPlan) -> ExecutionRecord:
        with self._lock:
            existing = self._records.get(action.action_id)

            if existing is not None:
                raise ValueError(
                    f"Action already has an execution attempt: "
                    f"{existing.execution_id}"
                )

            if action.status in self.BLOCKED_STATUSES:
                raise ValueError(
                    f"Action cannot start execution from status: "
                    f"{action.status.value}"
                )

            record = ExecutionRecord(
                action_id=action.action_id,
                execution_id=f"exec-{uuid4().hex}",
                status=ActionStatus.EXECUTING,
            )

            self._records[action.action_id] = record

            return record

    def get_execution(
        self,
        action_id: str,
    ) -> ExecutionRecord | None:
        with self._lock:
            return self._records.get(action_id)

    def has_execution(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._records

    def complete_execution(
        self,
        action: ActionPlan,
    ) -> ExecutionRecord:
        with self._lock:
            existing = self._records.get(action.action_id)

            if existing is None:
                raise ValueError(
                    "No execution attempt exists for this action."
                )

            updated = ExecutionRecord(
                action_id=existing.action_id,
                execution_id=existing.execution_id,
                status=action.status,
                created_at=existing.created_at,
            )

            self._records[action.action_id] = updated

            return updated

    def clear(self, action_id: str) -> None:
        with self._lock:
            self._records.pop(action_id, None)
