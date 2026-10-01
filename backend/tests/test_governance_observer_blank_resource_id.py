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


@pytest.mark.parametrize("resource_id", ["", "   ", "\t", "\n"])
def test_observer_rejects_blank_resource_id(resource_id):
    with pytest.raises(ValueError, match="resource_id cannot be empty"):
        ResourceObserver().observe(
            Provider(), "ec2", resource_id
        )
