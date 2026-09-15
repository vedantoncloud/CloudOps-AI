from fastapi.testclient import TestClient

from autonomy.control_loop_api import router


def test_control_loop_accepts_default_aws_provider():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    payload = {
        "action_id": "provider-api-1",
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-provider-123",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }

    response = client.post("/autonomy/control-loop/evaluate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "aws"
    assert data["action_id"] == "provider-api-1"
    assert data["evidence"]["provider"] == "aws"


def test_control_loop_accepts_explicit_aws_provider():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    payload = {
        "provider": "AWS",
        "action_id": "provider-api-2",
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-provider-456",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }

    response = client.post("/autonomy/control-loop/evaluate", json=payload)

    assert response.status_code == 200
    assert response.json()["provider"] == "aws"


def test_control_loop_rejects_unknown_provider():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    payload = {
        "provider": "azure",
        "action_id": "provider-api-3",
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-provider-789",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }

    response = client.post("/autonomy/control-loop/evaluate", json=payload)

    assert response.status_code == 400
    assert "unknown cloud provider" in response.json()["detail"]


def test_provider_registry_contains_aws():
    from autonomy.control_loop_api import provider_registry

    assert provider_registry.has("aws")
    assert provider_registry.get("aws").provider_name == "aws"


def test_control_loop_exposes_provider_resource_context():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    payload = {
        "action_id": "provider-context-1",
        "action_type": "investigate_cpu_capacity",
        "resource_type": "ec2",
        "resource_id": "i-context-123",
        "reason": "High CPU utilization detected",
        "risk": "medium",
        "requires_approval": True,
        "field": "instance_type",
        "desired_value": "t3.large",
        "current_value": "t3.medium",
    }

    response = client.post("/autonomy/control-loop/evaluate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "aws"
    assert data["evidence"]["resource_context"]["provider"] == "aws"
    assert data["evidence"]["resource_context"]["resource_id"] == "i-context-123"
    assert data["evidence"]["resource_context"]["resource_type"] == "ec2"
    assert data["evidence"]["resource_context"]["observation"]["read_only"] is True
