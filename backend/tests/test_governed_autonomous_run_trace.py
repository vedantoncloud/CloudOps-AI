from __future__ import annotations

from types import SimpleNamespace

from autonomy.governed_autonomous_run import GovernedAutonomousRun


class FakeGovernedPipeline:
    def __init__(self, governance):
        self.governance = governance
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.governance


class FakeLifecycle:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            outcome="completed",
            completed=True,
            blocked=False,
            requires_human_approval=False,
            evidence={"verification": "passed"},
        )


def governance_allow():
    return SimpleNamespace(
        recommendation="proceed",
        blocked=False,
        requires_human_review=False,
        decision=SimpleNamespace(
            recommendation=SimpleNamespace(value="proceed"),
            confidence=0.95,
        ),
    )


def governance_deny():
    return SimpleNamespace(
        recommendation="deny",
        blocked=True,
        requires_human_review=False,
        decision=None,
    )


def governance_review():
    return SimpleNamespace(
        recommendation="review",
        blocked=False,
        requires_human_review=True,
        decision=None,
    )


def action():
    return SimpleNamespace(
        action_id="action-trace-1",
        target=SimpleNamespace(resource_id="i-trace"),
    )


def provider():
    return SimpleNamespace(provider_name="aws")


def test_run_id_is_generated_when_not_supplied():
    lifecycle = FakeLifecycle()
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=lifecycle,
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
    )

    assert result.run_id
    assert result.evidence["run_id"] == result.run_id


def test_supplied_run_id_is_preserved():
    lifecycle = FakeLifecycle()
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=lifecycle,
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-fixed-001",
    )

    assert result.run_id == "trace-fixed-001"
    assert result.evidence["run_id"] == "trace-fixed-001"
    assert result.evidence["trace"]["run_id"] == "trace-fixed-001"


def test_trace_links_decision_action_and_resource():
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=FakeLifecycle(),
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-linked",
    )

    trace = result.evidence["trace"]
    assert trace["run_id"] == "trace-linked"
    assert trace["decision"] == "proceed"
    assert trace["action_id"] == "action-trace-1"
    assert trace["resource_id"] == "i-trace"


def test_trace_survives_lifecycle_completion():
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=FakeLifecycle(),
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-complete",
    )

    assert result.outcome == "completed"
    assert result.lifecycle is not None
    assert result.evidence["run_id"] == "trace-complete"
    assert result.evidence["lifecycle_outcome"] == "completed"
    assert result.evidence["lifecycle"]["verification"] == "passed"


def test_trace_is_preserved_when_governance_denies():
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_deny()),
        lifecycle=FakeLifecycle(),
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-denied",
    )

    assert result.outcome == "blocked"
    assert result.run_id == "trace-denied"
    assert result.evidence["run_id"] == "trace-denied"
    assert result.evidence["execution_flow"] == "stopped_by_governance"


def test_trace_is_preserved_for_human_review():
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_review()),
        lifecycle=FakeLifecycle(),
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-review",
    )

    assert result.outcome == "review"
    assert result.run_id == "trace-review"
    assert result.evidence["run_id"] == "trace-review"
    assert result.evidence["execution_flow"] == "stopped_for_human_review"


def test_blank_run_id_gets_a_generated_identifier():
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=FakeLifecycle(),
    )

    result = runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="   ",
    )

    assert result.run_id.strip()
    assert result.evidence["run_id"] == result.run_id


def test_existing_lifecycle_receives_decision_without_trace_contract_change():
    lifecycle = FakeLifecycle()
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(governance_allow()),
        lifecycle=lifecycle,
    )

    runner.run(
        provider=provider(),
        action=action(),
        resource_type="ec2",
        resource_id="i-trace",
        run_id="trace-lifecycle",
    )

    assert lifecycle.calls[0]["decision"].recommendation.value == "proceed"
    assert "run_id" not in lifecycle.calls[0]
