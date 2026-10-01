from autonomy.resource_governance import ResourceGovernanceEngine
from autonomy.resource_observer import ResourceObserver
from autonomy.resource_policy import ResourcePolicy


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "state": "running",
            "health": "healthy",
            "tags": {"environment": "test"},
            "metadata": {"owner": "platform"},
        }


def test_governance_report_contains_expected_resource_contract():
    policy = ResourcePolicy(
        allowed_providers={"aws"},
        allowed_resource_types={"ec2"},
        required_metadata={"owner"},
        require_read_only=True,
    )
    engine = ResourceGovernanceEngine(
        observer=ResourceObserver()
    )
    engine.policy_engine.policy = policy

    result = engine.inspect(
        Provider(),
        "ec2",
        "i-task55",
    )

    report = engine.report(result)

    assert report["provider"] == "aws"
    assert report["resource_type"] == "ec2"
    assert report["resource_id"] == "i-task55"
    assert report["read_only"] is True
    assert report["decision"] == "allow"
    assert report["allowed_for_decision"] is True
    assert report["blocked"] is False
    assert report["requires_human_review"] is False
    assert "evidence" in report
