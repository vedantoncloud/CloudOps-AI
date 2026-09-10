from dataclasses import dataclass, field
from typing import Any

from autonomy.action_models import ActionPlan, RiskLevel
from autonomy.decision_gitops import (
    DecisionGitOpsBridge,
    DecisionGitOpsResult,
)
from autonomy.decision_intelligence import (
    DecisionContext,
    DecisionIntelligenceEngine,
    DecisionRecommendation,
    DecisionResult,
)
from autonomy.gitops import GitOpsChangeSet
from autonomy.memory_lifecycle import MemoryLifecycleRecorder
from autonomy.operational_memory import (
    MemoryOutcome,
    OperationalMemory,
)
from autonomy.policy_engine import PolicyEngine
from autonomy.simulator import SimulationResult


@dataclass(frozen=True)
class ControlLoopResult:
    action: ActionPlan
    decision: DecisionResult
    gitops: DecisionGitOpsResult | None
    memory: OperationalMemory | None
    stage_results: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False


class AutonomousControlLoop:
    """Bounded orchestration layer for the CloudOps-AI control loop."""

    def __init__(
        self,
        *,
        decision_engine: DecisionIntelligenceEngine | None = None,
        gitops_bridge: DecisionGitOpsBridge | None = None,
        memory_recorder: MemoryLifecycleRecorder | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.decision_engine = (
            decision_engine
            if decision_engine is not None
            else DecisionIntelligenceEngine()
        )
        self.gitops_bridge = (
            gitops_bridge
            if gitops_bridge is not None
            else DecisionGitOpsBridge()
        )
        self.memory_recorder = (
            memory_recorder
            if memory_recorder is not None
            else MemoryLifecycleRecorder()
        )
        self.policy_engine = (
            policy_engine
            if policy_engine is not None
            else PolicyEngine()
        )

    def evaluate(
        self,
        *,
        action: ActionPlan,
        decision_context: DecisionContext | None = None,
        field: str = "desired_state",
        desired_value: Any = None,
        current_value: Any | None = None,
        gitops_reason: str | None = None,
        gitops_metadata: dict[str, Any] | None = None,
    ) -> ControlLoopResult:
        if decision_context is None:
            decision_context = DecisionContext(
                resource_id=action.target.resource_id,
                resource_type=action.target.resource_type,
                action=action,
            )

        if decision_context.action.action_id != action.action_id:
            raise ValueError(
                "decision context action does not match supplied action"
            )

        stage_results: dict[str, Any] = {
            "action_planned": True,
            "policy_checked": False,
            "decision_evaluated": False,
            "gitops_proposed": False,
        }

        # Policy remains a hard governance boundary.
        policy_result = self.policy_engine.evaluate(action)
        stage_results["policy_checked"] = True
        stage_results["policy_result"] = policy_result

        if getattr(policy_result, "allowed", True) is False:
            decision = DecisionResult(
                resource_id=action.target.resource_id,
                action_id=action.action_id,
                recommendation=DecisionRecommendation.BLOCK,
                risk=RiskLevel.CRITICAL,
                confidence=1.0,
                reasons=["Policy engine blocked the action."],
                preventive=False,
                requires_human_review=True,
                evidence={"policy_blocked": True},
            )

            stage_results["decision_evaluated"] = True

            return ControlLoopResult(
                action=action,
                decision=decision,
                gitops=None,
                memory=None,
                stage_results=stage_results,
                blocked=True,
            )

        decision = self.decision_engine.evaluate(decision_context)
        stage_results["decision_evaluated"] = True
        stage_results["decision_recommendation"] = (
            decision.recommendation.value
        )

        if decision.recommendation == DecisionRecommendation.BLOCK:
            stage_results["gitops_proposed"] = False

            return ControlLoopResult(
                action=action,
                decision=decision,
                gitops=self.gitops_bridge.create_blocked_result(decision),
                memory=None,
                stage_results=stage_results,
                blocked=True,
            )

        gitops_result = self.gitops_bridge.create_proposal(
            decision,
            field=field,
            desired_value=desired_value,
            current_value=current_value,
            reason=gitops_reason,
            metadata=gitops_metadata,
        )

        stage_results["gitops_proposed"] = gitops_result.created

        return ControlLoopResult(
            action=action,
            decision=decision,
            gitops=gitops_result,
            memory=None,
            stage_results=stage_results,
            blocked=False,
        )

    def record_success(
        self,
        result: ControlLoopResult,
        *,
        lesson: str,
        metadata: dict[str, Any] | None = None,
    ) -> ControlLoopResult:
        memory = self.memory_recorder.record_success(
            result.action,
            lesson=lesson,
            metadata=metadata,
        )

        return ControlLoopResult(
            action=result.action,
            decision=result.decision,
            gitops=result.gitops,
            memory=memory,
            stage_results={
                **result.stage_results,
                "memory_recorded": True,
                "memory_outcome": MemoryOutcome.SUCCESS.value,
            },
            blocked=result.blocked,
        )

    def record_failure(
        self,
        result: ControlLoopResult,
        *,
        lesson: str,
        metadata: dict[str, Any] | None = None,
    ) -> ControlLoopResult:
        memory = self.memory_recorder.record_failure(
            result.action,
            lesson=lesson,
            metadata=metadata,
        )

        return ControlLoopResult(
            action=result.action,
            decision=result.decision,
            gitops=result.gitops,
            memory=memory,
            stage_results={
                **result.stage_results,
                "memory_recorded": True,
                "memory_outcome": MemoryOutcome.FAILURE.value,
            },
            blocked=result.blocked,
        )

    def record_rollback(
        self,
        result: ControlLoopResult,
        *,
        lesson: str,
        metadata: dict[str, Any] | None = None,
    ) -> ControlLoopResult:
        memory = self.memory_recorder.record_rollback(
            result.action,
            lesson=lesson,
            metadata=metadata,
        )

        return ControlLoopResult(
            action=result.action,
            decision=result.decision,
            gitops=result.gitops,
            memory=memory,
            stage_results={
                **result.stage_results,
                "memory_recorded": True,
                "memory_outcome": MemoryOutcome.ROLLED_BACK.value,
            },
            blocked=result.blocked,
        )

