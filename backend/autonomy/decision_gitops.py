from dataclasses import dataclass
from typing import Any

from autonomy.decision_intelligence import (
    DecisionRecommendation,
    DecisionResult,
)
from autonomy.gitops import (
    GitOpsChange,
    GitOpsChangeSet,
    GitOpsEngine,
)


@dataclass(frozen=True)
class DecisionGitOpsResult:
    decision: DecisionResult
    change_set: GitOpsChangeSet | None
    created: bool
    reason: str


class DecisionGitOpsBridge:
    """Translate governed AI decisions into declarative GitOps proposals."""

    def __init__(self, engine: GitOpsEngine | None = None) -> None:
        if engine is None:
            self.engine = GitOpsEngine()
        else:
            self.engine = engine

    def create_proposal(
        self,
        decision: DecisionResult,
        *,
        field: str,
        desired_value: Any,
        current_value: Any | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionGitOpsResult:
        if not field.strip():
            raise ValueError("field cannot be empty")

        if decision.recommendation == DecisionRecommendation.BLOCK:
            return DecisionGitOpsResult(
                decision=decision,
                change_set=None,
                created=False,
                reason="Blocked decision cannot create a GitOps change.",
            )

        change = GitOpsChange(
            resource_type="infrastructure",
            resource_id=decision.resource_id,
            field=field,
            desired_value=desired_value,
            current_value=current_value,
            reason=reason
            or (
                decision.reasons[0]
                if decision.reasons
                else "Decision intelligence recommendation"
            ),
        )

        requires_approval = decision.requires_human_review

        # Preserve the complete decision evidence alongside the GitOps proposal.
        decision_evidence = dict(decision.evidence)

        change_set = self.engine.create_change_set(
            source_action_id=decision.action_id,
            changes=[change],
            requires_approval=requires_approval,
            commit_message=(
                f"cloudops-ai: {decision.recommendation.value} "
                f"change for {decision.resource_id}"
            ),
            metadata={
                "decision_recommendation": decision.recommendation.value,
                "decision_risk": decision.risk.value,
                "decision_confidence": decision.confidence,
                "preventive": decision.preventive,
                **decision_evidence,
                **(metadata or {}),
            },
        )

        return DecisionGitOpsResult(
            decision=decision,
            change_set=change_set,
            created=True,
            reason=(
                "GitOps change proposal created from Decision Intelligence."
            ),
        )

    def create_blocked_result(
        self,
        decision: DecisionResult,
    ) -> DecisionGitOpsResult:
        return DecisionGitOpsResult(
            decision=decision,
            change_set=None,
            created=False,
            reason="Decision is blocked; infrastructure change is not proposed.",
        )
