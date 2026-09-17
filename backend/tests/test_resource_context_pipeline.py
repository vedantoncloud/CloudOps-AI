from dataclasses import dataclass

from autonomy.resource_context_pipeline import ResourceContextPipeline


@dataclass
class FakeProvider:
    provider_name: str = "aws"

    def get_resource(self, *, resource_type: str, resource_id: str):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "state": "running",
            "health": "healthy",
            "tags": {"Environment": "test"},
        }


class FakeDiscovery:
    def __init__(self, resource_ids):
        self.resource_ids = set(resource_ids)

    def list_resources(self, *, provider, resource_type):
        return [
            type("Resource", (), {"resource_id": resource_id})()
            for resource_id in self.resource_ids
        ]


def test_pipeline_builds_resource_context():
    pipeline = ResourceContextPipeline(
        discovery=FakeDiscovery({"i-123"}),
    )

    result = pipeline.build(
        provider=FakeProvider(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.discovered is True
    assert result.allowed_for_decision is True
    assert result.blocked is False
    assert result.resource_context.provider == "aws"
    assert result.resource_context.resource_id == "i-123"
    assert result.resource_context.resource_type == "ec2"
    assert result.resource_context.observation["state"] == "running"
    assert result.evidence["pipeline_outcome"] == "allowed"


def test_pipeline_preserves_discovery_state():
    pipeline = ResourceContextPipeline(
        discovery=FakeDiscovery(set()),
    )

    result = pipeline.build(
        provider=FakeProvider(),
        resource_type="ec2",
        resource_id="i-missing",
    )

    assert result.discovered is False
    # Governance remains authoritative for decision eligibility.
    assert result.allowed_for_decision is True
    assert result.evidence["discovered"] is False


def test_pipeline_exposes_governance_result():
    pipeline = ResourceContextPipeline(
        discovery=FakeDiscovery({"i-123"}),
    )

    result = pipeline.build(
        provider=FakeProvider(),
        resource_type="ec2",
        resource_id="i-123",
    )

    assert result.governance is not None
    assert result.governance.evidence["governance_gate"] == "allow"
    assert result.evidence["policy_decision"] == "allow"
