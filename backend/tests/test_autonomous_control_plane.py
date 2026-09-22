from types import SimpleNamespace

from autonomy.autonomous_control_plane import AutonomousControlPlane


class FakeGoverned:
    def __init__(self, allowed=True, blocked=False, review=False):
        self.allowed_for_decision = allowed
        self.blocked = blocked
        self.requires_human_review = review
        self.decision = SimpleNamespace(recommendation=SimpleNamespace(value="proceed"))
        self.evidence = {"source": "test"}


class FakePipeline:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeLifecycle:
    def __init__(self):
        self.calls = []

    def run(self, action, **kwargs):
        self.calls.append((action, kwargs))
        return SimpleNamespace(
            outcome="completed",
            execution=SimpleNamespace(executed=True),
            evidence={"lifecycle": "ok"},
        )


def test_allow_flows_into_existing_lifecycle():
    governed = FakeGoverned()
    pipeline = FakePipeline(governed)
    lifecycle = FakeLifecycle()
    action = SimpleNamespace(action_id="a1")

    result = AutonomousControlPlane(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    ).run(
        provider="aws",
        action=action,
        resource_type="ec2",
        resource_id="i-1",
        dry_run=True,
    )

    assert result.lifecycle is not None
    assert result.outcome == "completed"
    assert result.executed is True
    assert len(lifecycle.calls) == 1
    assert lifecycle.calls[0][1]["decision"] is governed.decision


def test_governance_block_stops_before_lifecycle():
    governed = FakeGoverned(allowed=False, blocked=True)
    pipeline = FakePipeline(governed)
    lifecycle = FakeLifecycle()

    result = AutonomousControlPlane(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    ).run(
        provider="aws",
        action=SimpleNamespace(action_id="a2"),
        resource_type="ec2",
        resource_id="i-2",
    )

    assert result.lifecycle is None
    assert result.outcome == "blocked"
    assert result.executed is False
    assert lifecycle.calls == []
    assert result.evidence["execution_flow"] == "stopped_before_lifecycle"


def test_governance_review_stops_before_lifecycle():
    governed = FakeGoverned(allowed=False, review=True)
    pipeline = FakePipeline(governed)
    lifecycle = FakeLifecycle()

    result = AutonomousControlPlane(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    ).run(
        provider="aws",
        action=SimpleNamespace(action_id="a3"),
        resource_type="ec2",
        resource_id="i-3",
    )

    assert result.lifecycle is None
    assert result.outcome == "awaiting_approval"
    assert lifecycle.calls == []


def test_all_decision_context_reaches_governed_pipeline():
    governed = FakeGoverned()
    pipeline = FakePipeline(governed)
    lifecycle = FakeLifecycle()

    AutonomousControlPlane(
        governed_pipeline=pipeline,
        lifecycle=lifecycle,
    ).run(
        provider="aws",
        action=SimpleNamespace(action_id="a4"),
        resource_type="ec2",
        resource_id="i-4",
        blast_radius="br",
        dependency="dep",
        prediction="pred",
        cost_opportunity="cost",
        security_findings=["finding"],
        simulation="sim",
        memories=["memory"],
        approved_by="operator",
        idempotency_key="key",
        idempotency_seen=True,
        dry_run=False,
    )

    call = pipeline.calls[0]
    assert call["blast_radius"] == "br"
    assert call["dependency"] == "dep"
    assert call["prediction"] == "pred"
    assert call["cost_opportunity"] == "cost"
    assert call["security_findings"] == ["finding"]
    assert call["simulation"] == "sim"
    assert call["memories"] == ["memory"]
