import pytest
from fastapi.testclient import TestClient

import main


@pytest.mark.parametrize(
    "path,method_name",
    [
        ("/cloud/aws/rds/instances?max_records=20", "get_rds_instances"),
        ("/cloud/aws/rds/snapshots?max_records=20", "get_rds_snapshots"),
    ],
)
@pytest.mark.parametrize("marker", ["", "   ", "x" * 4097])
def test_rds_inventory_rejects_blank_or_oversized_request_markers(
    monkeypatch, path, method_name, marker
):
    called = False

    def unexpected_provider_call(*args, **kwargs):
        nonlocal called
        called = True
        pytest.fail("invalid RDS marker must be rejected before AWS is called")

    monkeypatch.setattr(main.aws_service, method_name, unexpected_provider_call)
    response = TestClient(main.app).get(path, params={"marker": marker})

    assert response.status_code == 400
    assert response.json()["detail"].startswith(
        "marker must contain 1 to 4096"
    )
    assert called is False
