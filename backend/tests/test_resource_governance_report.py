from autonomy.resource_governance import GovernedResourceObservation
from autonomy.resource_governance_report import build_resource_governance_report
from autonomy.resource_observer import ResourceObservation
from autonomy.resource_policy import ResourcePolicy, ResourcePolicyDecision, ResourcePolicyResult


def test_resource_governance_report_contains_resource_identity():
    observation = ResourceObservation(
        provider="aws",
        resource_type="ec2",
        resource_id="i-test",
    )

    result = ResourcePolicyResult(
        decision=ResourcePolicyDecision.ALLOW,
        reasons=["ok"],
    )

    governed = GovernedResourceObservation(
        observation=observation,
        policy=result,
        allowed_for_decision=True,
    )

    report = build_resource_governance_report(
        governed,
        ResourcePolicy(),
    )

    assert report["provider"] == "aws"
    assert report["resource_type"] == "ec2"
    assert report["resource_id"] == "i-test"
    assert report["decision"] == "allow"


def test_engine_report_integrates_governance_report():
    from autonomy.resource_governance import ResourceGovernanceEngine
    from autonomy.resource_observer import ResourceObservation
    from autonomy.resource_policy import ResourcePolicy, ResourcePolicyEngine

    class Provider:
        provider_name = "aws"

    class Observer:
        def observe(self, provider, resource_type, resource_id):
            return ResourceObservation(
                provider="aws",
                resource_type=resource_type,
                resource_id=resource_id,
                data={
                    "metadata": {"environment": "test"},
                    "tags": {"team": "platform"},
                },
                read_only=True,
            )

    policy = ResourcePolicy(
        allowed_providers={"aws"},
        allowed_resource_types={"ec2"},
        required_metadata={"environment"},
    )

    engine = ResourceGovernanceEngine(
        observer=Observer(),
        policy_engine=ResourcePolicyEngine(policy),
    )

    result = engine.inspect(Provider(), "ec2", "i-123")
    report = engine.report(result)

    assert report["provider"] == "aws"
    assert report["resource_type"] == "ec2"
    assert report["resource_id"] == "i-123"
    assert report["decision"] == "allow"
    assert report["allowed_for_decision"] is True
    assert report["blocked"] is False
    assert report["requires_human_review"] is False
    assert report["read_only"] is True
    assert "evidence" in report
