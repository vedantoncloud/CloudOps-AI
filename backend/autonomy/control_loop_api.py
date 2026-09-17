from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.audit_api import audit_trail
from autonomy.aws_provider import AWSProvider
from autonomy.control_loop import AutonomousControlLoop
from autonomy.control_loop_governance import ControlLoopGovernanceGate
from autonomy.decision_intelligence import DecisionContext
from autonomy.gitops_api import registry as gitops_registry
from autonomy.provider_registry import ProviderRegistry
from autonomy.resource_context_pipeline import ResourceContextPipeline
from autonomy.resource_discovery import ResourceDiscovery

router = APIRouter(
    prefix="/autonomy/control-loop",
    tags=["autonomy-control-loop"],
)

provider_registry = ProviderRegistry()
provider_registry.register(AWSProvider())

# Shared governance gate. Tests and callers can inject a custom governance engine.
governance_gate = ControlLoopGovernanceGate()
resource_discovery = ResourceDiscovery(provider_registry)
resource_context_pipeline = ResourceContextPipeline(
    discovery=resource_discovery,
    governance_gate=governance_gate,
)


class ControlLoopEvaluateRequest(BaseModel):
    provider: str = Field(default="aws", min_length=1)
    action_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = True
    field: str = Field(min_length=1)
    desired_value: Any = None
    current_value: Any | None = None


class ControlLoopEvaluateResponse(BaseModel):
    action_id: str
    resource_id: str
    provider: str
    recommendation: str
    risk: str
    confidence: float
    preventive: bool
    requires_human_review: bool
    blocked: bool
    gitops_created: bool
    gitops_change_id: str | None
    gitops_status: str | None
    reasons: list[str]
    evidence: dict[str, Any]


def _audit_gate_result(action: ActionPlan, provider_name: str, gate_result: Any) -> None:
    decision = gate_result.decision.value
    event = (
        "control_loop_governance_blocked"
        if gate_result.blocked
        else (
            "control_loop_governance_review"
            if gate_result.requires_human_review
            else "control_loop_governance_allowed"
        )
    )
    audit_trail.record(
        action_id=action.action_id,
        action_type=event,
        resource_type=action.target.resource_type,
        resource_id=action.target.resource_id,
        event=event,
        old_status="pending",
        new_status=decision,
        details={
            "provider": provider_name,
            "policy_decision": decision,
            "governance_gate": gate_result.evidence.get("governance_gate"),
            "requires_human_review": gate_result.requires_human_review,
            "blocked": gate_result.blocked,
            "evidence": dict(gate_result.evidence),
        },
    )

    if gate_result.blocked:
        audit_trail.record(
            action_id=action.action_id,
            action_type="control_loop_blocked",
            resource_type=action.target.resource_type,
            resource_id=action.target.resource_id,
            event="control_loop_blocked",
            old_status="pending",
            new_status="blocked",
            details={
                "provider": provider_name,
                "policy_decision": decision,
                "governance_gate": gate_result.evidence.get("governance_gate"),
                "blocked": True,
                "evidence": dict(gate_result.evidence),
            },
        )


@router.post("/evaluate", response_model=ControlLoopEvaluateResponse)
def evaluate_control_loop(request: ControlLoopEvaluateRequest) -> ControlLoopEvaluateResponse:
    try:
        provider = provider_registry.get(request.provider)

        action = ActionPlan(
            action_id=request.action_id,
            action_type=request.action_type,
            target=ActionTarget(
                resource_type=request.resource_type,
                resource_id=request.resource_id,
            ),
            reason=request.reason,
            risk=request.risk,
            requires_approval=request.requires_approval,
            status=ActionStatus.PENDING_APPROVAL,
        )

        # Unified resource pipeline: discovery + observation + governance.
        pipeline = resource_context_pipeline.build(
            provider=provider,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
        )

        governance = pipeline.governance
        governance_evidence = {
            **dict(governance.evidence),
            "policy_decision": governance.decision.value,
            "allowed_for_decision": governance.allowed,
        }

        pipeline_evidence = dict(pipeline.evidence)

        if not pipeline.allowed_for_decision:
            _audit_gate_result(action, provider.provider_name, governance)
            recommendation = "deny" if pipeline.blocked else "review"

            return ControlLoopEvaluateResponse(
                action_id=action.action_id,
                resource_id=action.target.resource_id,
                provider=provider.provider_name,
                recommendation=recommendation,
                risk=request.risk.value,
                confidence=1.0,
                preventive=False,
                requires_human_review=pipeline.requires_human_review,
                blocked=pipeline.blocked,
                gitops_created=False,
                gitops_change_id=None,
                gitops_status=None,
                reasons=list(governance.resource.policy.reasons),
                evidence={
                    "provider": provider.provider_name,
                    "resource_pipeline": pipeline_evidence,
                    "resource_context": { "provider": getattr(pipeline.resource_context, "provider", pipeline.resource_context.observation.get("provider", provider.provider_name)), "resource_id": getattr(pipeline.resource_context, "resource_id", pipeline.resource_context.observation.get("resource_id", request.resource_id)), "resource_type": getattr(pipeline.resource_context, "resource_type", pipeline.resource_context.observation.get("resource_type", request.resource_type)), "observation": pipeline.resource_context.observation },
                    "governance": governance_evidence,
                },
            )

        context = DecisionContext(
            resource_id=request.resource_id,
            resource_type=request.resource_type,
            action=action,
            provider=provider.provider_name,
            resource_context=pipeline.resource_context,
        )

        result = AutonomousControlLoop().evaluate(
            action=action,
            decision_context=context,
            field=request.field,
            desired_value=request.desired_value,
            current_value=request.current_value,
        )

        gitops_change_id = None
        gitops_status = None
        gitops_created = False

        if result.gitops is not None:
            gitops_created = result.gitops.created
            if result.gitops.change_set is not None:
                change_set = result.gitops.change_set
                existing = gitops_registry.get(change_set.change_id)
                if existing is None:
                    existing = gitops_registry.register(change_set)
                gitops_change_id = existing.change_id
                gitops_status = existing.status.value

        audit_event = "control_loop_blocked" if result.blocked else "control_loop_evaluated"
        audit_status = (
            "blocked"
            if result.blocked
            else (
                gitops_status
                if gitops_status is not None
                else result.decision.recommendation.value
            )
        )

        audit_trail.record(
            action_id=result.action.action_id,
            action_type=audit_event,
            resource_type=result.action.target.resource_type,
            resource_id=result.action.target.resource_id,
            event=audit_event,
            old_status="pending",
            new_status=audit_status,
            details={
                "provider": provider.provider_name,
                "recommendation": result.decision.recommendation.value,
                "risk": result.decision.risk.value,
                "confidence": result.decision.confidence,
                "preventive": result.decision.preventive,
                "requires_human_review": result.decision.requires_human_review,
                "gitops_created": gitops_created,
                "gitops_change_id": gitops_change_id,
                "resource_pipeline": pipeline_evidence,
                "resource_context": { "provider": getattr(pipeline.resource_context, "provider", pipeline.resource_context.observation.get("provider", provider.provider_name)), "resource_id": getattr(pipeline.resource_context, "resource_id", pipeline.resource_context.observation.get("resource_id", request.resource_id)), "resource_type": getattr(pipeline.resource_context, "resource_type", pipeline.resource_context.observation.get("resource_type", request.resource_type)), "observation": pipeline.resource_context.observation },
                "governance": governance_evidence,
            },
        )

        return ControlLoopEvaluateResponse(
            action_id=result.action.action_id,
            resource_id=result.action.target.resource_id,
            provider=provider.provider_name,
            recommendation=result.decision.recommendation.value,
            risk=result.decision.risk.value,
            confidence=result.decision.confidence,
            preventive=result.decision.preventive,
            requires_human_review=result.decision.requires_human_review,
            blocked=result.blocked,
            gitops_created=gitops_created,
            gitops_change_id=gitops_change_id,
            gitops_status=gitops_status,
            reasons=result.decision.reasons,
            evidence={
                **dict(result.decision.evidence),
                "resource_pipeline": pipeline_evidence,
                "resource_context": { "provider": getattr(pipeline.resource_context, "provider", pipeline.resource_context.observation.get("provider", provider.provider_name)), "resource_id": getattr(pipeline.resource_context, "resource_id", pipeline.resource_context.observation.get("resource_id", request.resource_id)), "resource_type": getattr(pipeline.resource_context, "resource_type", pipeline.resource_context.observation.get("resource_type", request.resource_type)), "observation": pipeline.resource_context.observation },
                "governance": governance_evidence,
            },
        )

    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


