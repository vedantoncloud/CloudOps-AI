from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from auth import AccessControlMiddleware, Principal


class FakeAWSService:
    def get_ec2_instances(self, state=None, tag=None):
        return {
            "service": "ec2",
            "status": "healthy",
            "instances": [
                {"instance_id": "i-owned", "state": "running", "tags": {"CloudOpsTenantId": "tenant-a"}},
                {"instance_id": "i-other", "state": "stopped", "tags": {"CloudOpsTenantId": "tenant-b"}},
                {"instance_id": "i-untagged", "state": "running", "tags": {}},
            ],
        }

    def get_ec2_summary(self):
        raise AssertionError("tenant summary must be computed from scoped inventory")


def tenant_client(monkeypatch):
    monkeypatch.setattr(main, "aws_service", FakeAWSService())
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"token-a": Principal("alice", "reader", "tenant-a")},
    )
    return TestClient(app)


def test_ec2_inventory_hides_other_tenants_and_untagged_instances(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/instances",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert [item["instance_id"] for item in response.json()["instances"]] == ["i-owned"]


def test_ec2_summary_counts_only_the_authenticated_tenants_instances(monkeypatch):
    response = tenant_client(monkeypatch).get(
        "/cloud/aws/ec2/summary",
        headers={"Authorization": "Bearer token-a"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "service": "ec2",
        "status": "healthy",
        "total_instances": 1,
        "running_instances": 1,
        "stopped_instances": 0,
    }
