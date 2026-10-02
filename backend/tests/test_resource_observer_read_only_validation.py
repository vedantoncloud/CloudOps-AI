import pytest

from autonomy.resource_observer import ResourceObserver


class Provider:
    provider_name = "aws"

    def __init__(self, read_only_marker):
        self.read_only_marker = read_only_marker

    def get_resource(self, resource_type, resource_id):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": self.read_only_marker,
        }


@pytest.mark.parametrize("marker", [True, False])
def test_observer_preserves_boolean_read_only_values(marker):
    result = ResourceObserver().observe(
        Provider(marker), "ec2", "i-readonly-test"
    )

    assert result.read_only is marker


@pytest.mark.parametrize(
    "marker",
    ["false", "true", "", None, 0, 1, [], {}],
)
def test_observer_defaults_malformed_read_only_values_to_true(marker):
    result = ResourceObserver().observe(
        Provider(marker), "ec2", "i-readonly-test"
    )

    assert result.read_only is True


def test_observer_defaults_missing_read_only_value_to_true():
    class MissingReadOnlyProvider:
        provider_name = "aws"

        def get_resource(self, resource_type, resource_id):
            return {
                "provider": "aws",
                "resource_type": resource_type,
                "resource_id": resource_id,
            }

    result = ResourceObserver().observe(
        MissingReadOnlyProvider(), "ec2", "i-readonly-test"
    )

    assert result.read_only is True
