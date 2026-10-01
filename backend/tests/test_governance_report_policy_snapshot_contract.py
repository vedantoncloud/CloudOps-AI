from autonomy.resource_governance import ResourceGovernanceEngine


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "metadata": {},
            "tags": {},
        }


def test_governance_report_contains_policy_snapshot_and_evidence():
    engine = ResourceGovernanceEngine()
    result = engine.inspect(Provider(), "ec2", "i-task43")

    report = engine.report(result)

    assert report["decision"] == "allow"
    assert report["allowed_for_decision"] is True
    assert report["evidence"]["decision"] == "allow"
    assert report["evidence"]["allowed"] is True
    assert report["evidence"]["policy"]["allowed_providers"] == ["aws"]
    assert report["evidence"]["policy"]["allowed_resource_types"] == [
        "ec2",
        "s3",
    ]
