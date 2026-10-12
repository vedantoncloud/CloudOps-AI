import pytest

from autonomy.aws_provider import AWSProvider


@pytest.mark.parametrize(
    "resource_type",
    [
        None,
        123,
        [],
        {},
        "",
        "   ",
    ],
)
def test_get_resource_rejects_invalid_resource_type(resource_type):
    provider = AWSProvider()

    with pytest.raises(
        ValueError,
        match="resource_type must be a non-empty string",
    ):
        provider.get_resource(
            resource_type=resource_type,
            resource_id="i-test-123",
        )


@pytest.mark.parametrize(
    "resource_id",
    [
        None,
        123,
        [],
        {},
        "",
        "   ",
    ],
)
def test_get_resource_rejects_invalid_resource_id(resource_id):
    provider = AWSProvider()

    with pytest.raises(
        ValueError,
        match="resource_id must be a non-empty string",
    ):
        provider.get_resource(
            resource_type="ec2",
            resource_id=resource_id,
        )


def test_get_resource_preserves_valid_observation_response():
    provider = AWSProvider()

    result = provider.get_resource(
        resource_type="ec2",
        resource_id="i-test-123",
    )

    assert result == {
        "provider": "aws",
        "resource_type": "ec2",
        "resource_id": "i-test-123",
        "read_only": True,
    }


def test_get_resource_accepts_non_empty_whitespace_surrounded_strings():
    provider = AWSProvider()

    result = provider.get_resource(
        resource_type=" ec2 ",
        resource_id=" i-test-123 ",
    )

    assert result["resource_type"] == " ec2 "
    assert result["resource_id"] == " i-test-123 "
    assert result["read_only"] is True