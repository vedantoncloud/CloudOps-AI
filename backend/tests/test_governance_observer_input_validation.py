import pytest

from autonomy.resource_observer import ResourceObserver


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
        }


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "message"),
    [
        ("", "i-task39", "resource_type cannot be empty"),
        ("ec2", "", "resource_id cannot be empty"),
        ("   ", "i-task39", "resource_type cannot be empty"),
    ],
)
def test_observer_rejects_empty_identifiers(
    resource_type, resource_id, message
):
    with pytest.raises(ValueError, match=message):
        ResourceObserver().observe(
            Provider(), resource_type, resource_id
        )
