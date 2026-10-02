import pytest

from autonomy.resource_observer import ResourceObserver


class FakeProvider:
    provider_name = "aws"

    def __init__(self, metadata):
        self.metadata = metadata

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata": self.metadata,
            "tags": {},
        }


@pytest.mark.parametrize(
    "metadata",
    [None, [], "invalid-metadata", 42],
)
def test_observer_normalizes_non_dictionary_metadata(metadata):
    observation = ResourceObserver().observe(
        FakeProvider(metadata),
        resource_type="ec2",
        resource_id="i-observer-metadata",
    )

    assert observation.data["metadata"] == {}


def test_observer_preserves_dictionary_metadata():
    observation = ResourceObserver().observe(
        FakeProvider({"owner": "platform"}),
        resource_type="ec2",
        resource_id="i-observer-metadata",
    )

    assert observation.data["metadata"] == {"owner": "platform"}
