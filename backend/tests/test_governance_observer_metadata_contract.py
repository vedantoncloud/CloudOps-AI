from autonomy.resource_observer import ResourceObserver


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "metadata": {"owner": "platform"},
            "instance_type": "t3.micro",
        }


def test_observer_preserves_metadata_and_extra_attributes():
    result = ResourceObserver().observe(
        Provider(), "ec2", "i-task42"
    )

    assert result.data["metadata"]["owner"] == "platform"
    assert result.data["metadata"]["instance_type"] == "t3.micro"
