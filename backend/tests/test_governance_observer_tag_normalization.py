from autonomy.resource_observer import ResourceObserver


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "tags": [
                {"Key": "team", "Value": "platform"},
                {"key": "environment", "value": "test"},
            ],
        }


def test_observer_normalizes_provider_tag_list():
    result = ResourceObserver().observe(
        Provider(), "ec2", "i-task41"
    )

    assert result.data["tags"] == {
        "team": "platform",
        "environment": "test",
    }
