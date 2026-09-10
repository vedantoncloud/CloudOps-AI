from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Lock

from autonomy.action_models import ActionPlan, ActionStatus, RiskLevel


class GovernanceDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class GovernanceRecord:
    action_id: str
    decision: GovernanceDecision
    decided_by: str | None
    reason: str | None
    decided_at: str


class GovernanceManager:
    """Central governance layer for autonomous action approval."""

    def __init__(self) -> None:
        self._records: dict[str, GovernanceRecord] = {}
        self._lock = Lock()

    def submit(self, action: ActionPlan) -> GovernanceRecord:
        with self._lock:
            existing = self._records.get(action.action_id)
            if existing is not None:
                return existing

            record = GovernanceRecord(
                action_id=action.action_id,
                decision=GovernanceDecision.PENDING,
                decided_by=None,
                reason=None,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
            self._records[action.action_id] = record
            return record

    def approve(
        self,
        action: ActionPlan,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> GovernanceRecord:
        if not decided_by or not decided_by.strip():
            raise ValueError("decided_by cannot be empty")

        with self._lock:
            existing = self._records.get(action.action_id)
            if existing is None:
                raise ValueError("Action is not submitted for governance.")

            if existing.decision != GovernanceDecision.PENDING:
                raise ValueError(
                    f"Action is already decided: {existing.decision.value}"
                )

            record = GovernanceRecord(
                action_id=action.action_id,
                decision=GovernanceDecision.APPROVED,
                decided_by=decided_by,
                reason=reason,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
            self._records[action.action_id] = record

            action.status = ActionStatus.APPROVED
            return record

    def reject(
        self,
        action: ActionPlan,
        *,
        decided_by: str,
        reason: str,
    ) -> GovernanceRecord:
        if not decided_by or not decided_by.strip():
            raise ValueError("decided_by cannot be empty")
        if not reason or not reason.strip():
            raise ValueError("reason cannot be empty")

        with self._lock:
            existing = self._records.get(action.action_id)
            if existing is None:
                raise ValueError("Action is not submitted for governance.")

            if existing.decision != GovernanceDecision.PENDING:
                raise ValueError(
                    f"Action is already decided: {existing.decision.value}"
                )

            record = GovernanceRecord(
                action_id=action.action_id,
                decision=GovernanceDecision.REJECTED,
                decided_by=decided_by,
                reason=reason,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
            self._records[action.action_id] = record

            action.status = ActionStatus.CANCELLED
            return record

    def cancel(
        self,
        action: ActionPlan,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> GovernanceRecord:
        if not decided_by or not decided_by.strip():
            raise ValueError("decided_by cannot be empty")

        with self._lock:
            existing = self._records.get(action.action_id)
            if existing is None:
                raise ValueError("Action is not submitted for governance.")

            if existing.decision != GovernanceDecision.PENDING:
                raise ValueError(
                    f"Action is already decided: {existing.decision.value}"
                )

            record = GovernanceRecord(
                action_id=action.action_id,
                decision=GovernanceDecision.CANCELLED,
                decided_by=decided_by,
                reason=reason,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
            self._records[action.action_id] = record

            action.status = ActionStatus.CANCELLED
            return record

    def get_record(self, action_id: str) -> GovernanceRecord | None:
        with self._lock:
            return self._records.get(action_id)

    def list_pending(self) -> list[GovernanceRecord]:
        with self._lock:
            return [
                record
                for record in self._records.values()
                if record.decision == GovernanceDecision.PENDING
            ]
