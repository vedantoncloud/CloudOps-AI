from types import SimpleNamespace

import pytest

from autonomy.governed_autonomous_run import GovernedAutonomousRun


def _decision():
    return SimpleNamespace(
        recommendation=SimpleNamespace(value="PROCEED"),
        confidence=0.9,
    )


def _governance():
    return SimpleNamespace(
        blocked=False,
        requires_human_review=False,
        recommendation="PROCEED",
        decision=_decision(),
        evidence={"governance_reason": "allowed"},
    )


class FakeGovernedPipeline:
    def evaluate(self, **kwargs):
        return _governance()


class SuccessfulLifecycle:
    def run(self, **kwargs):
        return SimpleNamespace(
            outcome="completed",
            completed=True,
            evidence={"lifecycle_stage": "verified"},
        )


class FailingLifecycle:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        raise self.error


def _run(lifecycle, run_id="run-reliability-001"):
    runner = GovernedAutonomousRun(
        governed_pipeline=FakeGovernedPipeline(),
        lifecycle=lifecycle,
    )
    action = SimpleNamespace(action_id="action-001")
    return runner.run(
        provider=SimpleNamespace(provider_name="aws"),
        action=action,
        resource_type="ec2",
        resource_id="i-001",
        dry_run=True,
        run_id=run_id,
    )


def test_lifecycle_exception_becomes_failed_run():
    result = _run(FailingLifecycle(RuntimeError("executor unavailable")))

    assert result.outcome == "failed"
    assert result.execution_started is True
    assert result.lifecycle is None
    assert result.completed is False


def test_failure_preserves_run_id():
    result = _run(
        FailingLifecycle(RuntimeError("boom")),
        run_id="trace-123",
    )

    assert result.run_id == "trace-123"
    assert result.evidence["run_id"] == "trace-123"
    assert result.evidence["trace"]["run_id"] == "trace-123"


def test_failure_contains_safe_exception_evidence():
    result = _run(FailingLifecycle(ValueError("invalid execution state")))

    failure = result.evidence["failure"]

    assert failure["stage"] == "autonomous_lifecycle"
    assert failure["exception_type"] == "ValueError"
    assert failure["message"] == "invalid execution state"
    assert result.evidence["execution_flow"] == "lifecycle_failed"
    assert result.evidence["lifecycle_outcome"] == "failed"


def test_failure_does_not_retry():
    lifecycle = FailingLifecycle(RuntimeError("one attempt only"))

    result = _run(lifecycle)

    assert lifecycle.calls == 1
    assert result.outcome == "failed"


def test_governance_evidence_is_preserved_on_failure():
    result = _run(RuntimeErrorLifecycle())

    assert result.evidence["governance"]["governance_reason"] == "allowed"


def test_successful_lifecycle_path_is_unchanged():
    result = _run(SuccessfulLifecycle())

    assert result.outcome == "completed"
    assert result.execution_started is True
    assert result.completed is True
    assert result.evidence["execution_flow"] == "autonomous_lifecycle"
    assert result.evidence["lifecycle_outcome"] == "completed"
    assert result.evidence["lifecycle"]["lifecycle_stage"] == "verified"


class RuntimeErrorLifecycle:
    def run(self, **kwargs):
        raise RuntimeError("controlled failure")


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("runtime failure"),
        ValueError("validation failure"),
        TimeoutError("provider timeout"),
    ],
)
def test_different_lifecycle_failures_are_explicitly_failed(error):
    result = _run(FailingLifecycle(error))

    assert result.outcome == "failed"
    assert result.evidence["failure"]["stage"] == "autonomous_lifecycle"
    assert result.evidence["failure"]["exception_type"] == type(error).__name__
