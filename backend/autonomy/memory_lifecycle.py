from autonomy.action_models import ActionPlan, ActionStatus
from autonomy.operational_memory import MemoryOutcome, OperationalMemoryStore


class MemoryLifecycleRecorder:
    """Records verified autonomy outcomes for future decision support."""

    def __init__(self, store: OperationalMemoryStore | None = None) -> None:
        if store is None:
            self.store = OperationalMemoryStore()
        else:
            self.store = store

    def record_outcome(
        self,
        action: ActionPlan,
        *,
        outcome: MemoryOutcome,
        lesson: str,
        metadata: dict | None = None,
    ):
        if action.status not in {
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.ROLLED_BACK,
        }:
            raise ValueError(
                "Only completed, failed, or rolled-back actions can be recorded"
            )

        return self.store.remember(
            memory_id=f"memory-{action.action_id}",
            resource_id=action.target.resource_id,
            resource_type=action.target.resource_type,
            situation=action.reason,
            action=action.action_type,
            outcome=outcome,
            lesson=lesson,
            metadata={
                "action_id": action.action_id,
                "risk": action.risk.value,
                "status": action.status.value,
                **(metadata or {}),
            },
        )

    def record_success(
        self,
        action: ActionPlan,
        *,
        lesson: str,
        metadata: dict | None = None,
    ):
        return self.record_outcome(
            action,
            outcome=MemoryOutcome.SUCCESS,
            lesson=lesson,
            metadata=metadata,
        )

    def record_failure(
        self,
        action: ActionPlan,
        *,
        lesson: str,
        metadata: dict | None = None,
    ):
        return self.record_outcome(
            action,
            outcome=MemoryOutcome.FAILURE,
            lesson=lesson,
            metadata=metadata,
        )

    def record_rollback(
        self,
        action: ActionPlan,
        *,
        lesson: str,
        metadata: dict | None = None,
    ):
        return self.record_outcome(
            action,
            outcome=MemoryOutcome.ROLLED_BACK,
            lesson=lesson,
            metadata=metadata,
        )

    def recall_for_action(
        self,
        *,
        resource_type: str,
        situation: str,
        action_type: str | None = None,
    ):
        return self.store.find_similar(
            resource_type=resource_type,
            situation=situation,
            action=action_type,
        )

    def lessons_for_action(
        self,
        *,
        resource_type: str,
        situation: str,
    ):
        return self.store.lessons_for(
            resource_type=resource_type,
            situation=situation,
        )
