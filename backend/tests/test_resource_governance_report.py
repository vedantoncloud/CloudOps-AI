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
