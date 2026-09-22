from dataclasses import dataclass

import pytest

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.decision_intelligence import DecisionRecommendation
from autonomy.governed_decision_pipeline import GovernedDecisionPipeline


@dataclass
class FakeProvider:
    provider_name: str = "aws"


def make_action(resource_id="i-123"):
    return ActionPlan(
        action_id="governed-decision-1",
        action_type="investigate_cpu_capacity",
        target=ActionTarget(resource_type="ec2", resource_id=resource_id),
        reason="High CPU utilization detected",
        risk=RiskLevel.MEDIUM,
        requires_approval=True,
        status=ActionStatus.PENDING_APPROVAL,
    )


def make_pipeline_result(
    *,
    allowed=True,
    review=False,
    blocked=False,
    resource_id="i-123",
):
    context = type(
        "Context",
        (),
        {
            "provider": "aws",
            "resource_id": resource_id,
            "resource_type": "ec2",
            "observation": {
                "provider": "aws",
                "resource_type": "ec2",
                "resource_id": resource_id,
                "read_only": True,
                "state": "running",
                "health": "healthy",
            },
        },
    )()

    governance = type(
        "Governance",
        (),
        {
            "evidence": {
                "policy_decision": (
                    "allow" if allowed else "review" if review else "deny"
                )
            }
        },
    )()

    return type(
        "PipelineResult",
        (),
        {
            "provider": "aws",
            "resource_type": "ec2",
            "resource_id": resource_id,
            "allowed_for_decision": allowed,
            "requires_human_review": review,
            "blocked": blocked,
            "governance": governance,
            "resource_context": context,
            "evidence": {
                "discovered": True,
                "pipeline_outcome": (
                    "allowed" if allowed else "review" if review else "blocked"
                ),
            },
        },
    )()


class FakePipeline:
    def __init__(self, result):
        self.result = result

    def build(self, **kwargs):
        return self.result


def test_allow_creates_decision():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.allowed_for_decision is True
    assert result.decision is not None
    assert result.evidence["decision_evaluated"] is True
    assert result.decision.evidence["provider"] == "aws"


def test_allow_preserves_resource_context():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    context = result.decision.evidence["resource_context"]
    assert context["provider"] == "aws"
    assert context["resource_id"] == "i-123"
    assert context["resource_type"] == "ec2"
    assert context["observation"]["read_only"] is True


def test_allow_propagates_decision_recommendation():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.recommendation in {item.value for item in DecisionRecommendation}


def test_action_resource_mismatch_is_rejected():
    with pytest.raises(ValueError, match="action target does not match resource_id"):
        GovernedDecisionPipeline(
            resource_pipeline=FakePipeline(make_pipeline_result())
        ).evaluate(
            provider=FakeProvider(),
            action=make_action("i-other"),
            resource_type="ec2",
            resource_id="i-123",
        )


def test_review_stops_before_decision():
    class ExplodingEngine:
        def evaluate(self, context):
            raise AssertionError("Decision Intelligence must not run")

    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(
            make_pipeline_result(
                allowed=False,
                review=True,
                resource_id="i-review",
            )
        ),
        decision_engine=ExplodingEngine(),
    ).evaluate(
        provider=FakeProvider(),
        action=make_action("i-review"),
        resource_type="ec2",
        resource_id="i-review",
    )

    assert result.decision is None
    assert result.requires_human_review is True
    assert result.evidence["decision_evaluated"] is False
    assert result.evidence["decision_flow"] == "stopped_by_governance"


def test_deny_stops_before_decision():
    class ExplodingEngine:
        def evaluate(self, context):
            raise AssertionError("Decision Intelligence must not run")

    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(
            make_pipeline_result(
                allowed=False,
                blocked=True,
                resource_id="i-deny",
            )
        ),
        decision_engine=ExplodingEngine(),
    ).evaluate(
        provider=FakeProvider(),
        action=make_action("i-deny"),
        resource_type="ec2",
        resource_id="i-deny",
    )

    assert result.decision is None
    assert result.blocked is True
    assert result.evidence["decision_flow"] == "stopped_by_governance"


def test_governance_evidence_is_preserved():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.evidence["governance"]["policy_decision"] == "allow"


def test_decision_evidence_is_preserved():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.evidence["decision_recommendation"] == result.decision.recommendation.value
    assert result.evidence["decision_confidence"] == result.decision.confidence


def test_provider_is_propagated_to_decision_context():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(make_pipeline_result())
    ).evaluate(
        provider=FakeProvider(),
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.decision.evidence["provider"] == "aws"


def test_review_keeps_pipeline_evidence():
    result = GovernedDecisionPipeline(
        resource_pipeline=FakePipeline(
            make_pipeline_result(
                allowed=False,
                review=True,
                resource_id="i-review",
            )
        )
    ).evaluate(
        provider=FakeProvider(),
        action=make_action("i-review"),
        resource_type="ec2",
        resource_id="i-review",
    )

    assert result.evidence["resource_pipeline"]["discovered"] is True
    assert result.decision is None
