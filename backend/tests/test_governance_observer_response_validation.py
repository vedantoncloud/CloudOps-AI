import pytest

from autonomy.resource_observer import ResourceObserver


class Provider:
    provider_name = "aws"

    def get_resource(self, resource_type, resource_id):
        return None


def test_observer_rejects_non_dictionary_provider_response():
    with pytest.raises(
        ValueError,
        match="must be a dictionary",
    ):
        ResourceObserver().observe(
            Provider(), "ec2", "i-task40"
        )
