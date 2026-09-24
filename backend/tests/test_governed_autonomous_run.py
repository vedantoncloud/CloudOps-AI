from __future__ import annotations

from types import SimpleNamespace

import pytest

from autonomy.autonomous_lifecycle import (
    AutonomousLifecycleResult,
    LifecycleOutcome,
)
from autonomy.execution_safety import (
    ExecutionSafetyDecision,
    ExecutionSafetyResult,
)
from autonomy.governed_autonomous_run import GovernedAutonomousRun
from autonomy.governed_decision_pipeline import GovernedDecisionPipelineResult


def make_action(resource_id: str = "i-123"):
    # The bridge forwards the action; these tests intentionally avoid
    # duplicating ActionPlan's constructor contract.
    return SimpleNamespace(
        action_id="action-123",
        target=SimpleNamespace(resource_id=resource_id),
    )


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeLifecycle:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return self.result


def governed_result(*, allowed, review=False, blocked=False, decision=None):
    resource_pipeline = SimpleNamespace(
        provider="aws",
        resource_type="ec2",
        resource_id="i-123",
    )
    return GovernedDecisionPipelineResult(
        resource_pipeline=resource_pipeline,
        decision=decision,
        allowed_for_decision=allowed,
        requires_human_review=review,
        blocked=blocked,
        evidence={"test": True},
    )


def lifecycle_result():
    safety = ExecutionSafetyResult(
        decision=ExecutionSafetyDecision.ALLOW,
        execution_allowed=True,
        requires_human_approval=False,
        reasons=[],
        evidence={},
        dry_run=True,
        destructive=False,
    )
    approval = SimpleNamespace(status=SimpleNamespace(value="approved"))
    return AutonomousLifecycleResult(
        action_id="action-123",
        outcome=LifecycleOutcome.COMPLETED,
        approval=approval,
        safety=safety,
        execution=SimpleNamespace(
            executed=True,
            successful=True,
            dry_run=True,
            message="dry run",
        ),
        verification=None,
        evidence={"lifecycle_test": True},
    )


def test_deny_stops_before_lifecycle():
    pipeline = FakePipeline(governed_result(allowed=False, blocked=True))
    lifecycle = FakeLifecycle(lifecycle_result())
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    )

    result = bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.outcome == "blocked"
    assert result.blocked
    assert not result.execution_started
    assert lifecycle.calls == []
    assert result.evidence["execution_flow"] == "stopped_by_governance"


def test_review_stops_before_lifecycle():
    pipeline = FakePipeline(governed_result(allowed=False, review=True))
    lifecycle = FakeLifecycle(lifecycle_result())
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    )

    result = bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.outcome == "review"
    assert result.requires_human_review
    assert not result.execution_started
    assert lifecycle.calls == []
    assert result.evidence["execution_flow"] == "stopped_for_human_review"


def test_allow_delegates_to_existing_lifecycle():
    decision = SimpleNamespace(recommendation=SimpleNamespace(value="proceed"))
    pipeline = FakePipeline(governed_result(allowed=True, decision=decision))
    lifecycle_result_value = lifecycle_result()
    lifecycle = FakeLifecycle(lifecycle_result_value)
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    )

    action = make_action()
    result = bridge.run(
        provider="aws",
        action=action,
        resource_type="ec2",
        resource_id="i-123",
        blast_radius="low",
        approved_by="operator",
        idempotency_key="key-1",
        dry_run=True,
    )

    assert result.outcome == LifecycleOutcome.COMPLETED
    assert result.execution_started
    assert result.lifecycle is lifecycle_result_value
    assert len(lifecycle.calls) == 1

    called_action, kwargs = lifecycle.calls[0]
    assert called_action is action
    assert kwargs["decision"] is decision
    assert kwargs["blast_radius"] == "low"
    assert kwargs["approved_by"] == "operator"
    assert kwargs["idempotency_key"] == "key-1"
    assert kwargs["dry_run"] is True


def test_governed_pipeline_receives_all_context_inputs():
    pipeline = FakePipeline(governed_result(allowed=False, review=True))
    lifecycle = FakeLifecycle(lifecycle_result())
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    )

    bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
        blast_radius="medium",
        dependency={"depends_on": ["x"]},
        prediction={"failure_probability": 0.1},
        cost_opportunity={"estimated_monthly_savings": 20},
        security_findings=[{"severity": "low"}],
        simulation={"safe": True},
        memories=[{"event": "previous"}],
    )

    kwargs = pipeline.calls[0]
    assert kwargs["blast_radius"] == "medium"
    assert kwargs["dependency"] == {"depends_on": ["x"]}
    assert kwargs["prediction"] == {"failure_probability": 0.1}
    assert kwargs["cost_opportunity"]["estimated_monthly_savings"] == 20
    assert kwargs["security_findings"] == [{"severity": "low"}]
    assert kwargs["simulation"] == {"safe": True}
    assert kwargs["memories"] == [{"event": "previous"}]


def test_action_resource_mismatch_is_delegated_to_governed_pipeline():
    class ValidatingPipeline:
        def evaluate(self, **kwargs):
            assert kwargs["action"].target.resource_id == "different"
            raise ValueError("action target does not match resource_id")

    bridge = GovernedAutonomousRun(governed_pipeline=ValidatingPipeline())

    with pytest.raises(ValueError, match="does not match"):
        bridge.run(
            provider="aws",
            action=make_action("different"),
            resource_type="ec2",
            resource_id="i-123",
        )


def test_allow_requires_decision_result():
    pipeline = FakePipeline(governed_result(allowed=True, decision=None))
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=FakeLifecycle(lifecycle_result()),
    )

    with pytest.raises(RuntimeError, match="without a decision"):
        bridge.run(
            provider="aws",
            action=make_action(),
            resource_type="ec2",
            resource_id="i-123",
        )


def test_governance_evidence_is_preserved():
    governed = governed_result(allowed=False, blocked=True)
    governed.evidence["governance_reason"] = "denied tag"
    bridge = GovernedAutonomousRun(
        governed_pipeline=FakePipeline(governed),
        lifecycle=FakeLifecycle(lifecycle_result()),
    )

    result = bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.evidence["governance"]["governance_reason"] == "denied tag"


def test_lifecycle_evidence_is_preserved():
    decision = SimpleNamespace(recommendation=SimpleNamespace(value="proceed"))
    pipeline = FakePipeline(governed_result(allowed=True, decision=decision))
    lifecycle_value = lifecycle_result()
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=FakeLifecycle(lifecycle_value),
    )

    result = bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.evidence["lifecycle"]["lifecycle_test"] is True


def test_dry_run_defaults_to_true():
    decision = SimpleNamespace(recommendation=SimpleNamespace(value="proceed"))
    pipeline = FakePipeline(governed_result(allowed=True, decision=decision))
    lifecycle = FakeLifecycle(lifecycle_result())
    bridge = GovernedAutonomousRun(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    )

    bridge.run(
        provider="aws",
        action=make_action(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert lifecycle.calls[0][1]["dry_run"] is True
