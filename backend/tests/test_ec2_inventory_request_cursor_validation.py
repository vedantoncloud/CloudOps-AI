import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize(
    "path,method_name",
    [
        ("/cloud/aws/ec2/instances?max_results=100", "get_ec2_instances"),
        ("/cloud/aws/ec2/volumes?max_results=100", "get_ec2_volumes"),
        ("/cloud/aws/ec2/snapshots?max_results=100", "get_ec2_snapshots"),
    ],
)
@pytest.mark.parametrize("cursor", ["", "   ", "x" * 4097])
def test_ec2_inventory_rejects_blank_or_oversized_request_cursors(
    monkeypatch, path, method_name, cursor
):
    called = False

    def unexpected_provider_call(*args, **kwargs):
        nonlocal called
        called = True
        pytest.fail("invalid pagination cursor must be rejected before AWS is called")

    monkeypatch.setattr(main.aws_service, method_name, unexpected_provider_call)
    response = TestClient(main.app).get(
        path,
        params={"next_token": cursor},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith(
        "next_token must contain 1 to 4096"
    )
    assert called is False
