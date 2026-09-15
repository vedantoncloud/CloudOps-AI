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


def test_resource_observer_normalizes_provider_neutral_state():
    from autonomy.aws_provider import AWSProvider
    from autonomy.resource_observer import ResourceObserver

    class FakeAWSService:
        def get_ec2_instances(self, state=None, tag_filter=None):
            return {}

        def get_ec2_summary(self):
            return {}

        def get_s3_buckets(self):
            return {}

    provider = AWSProvider(FakeAWSService())
    provider.get_resource = lambda resource_type, resource_id: {
        "provider": "aws",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "read_only": True,
        "state": "running",
        "health": "healthy",
        "tags": [
            {"Key": "Environment", "Value": "prod"},
            {"Key": "Team", "Value": "platform"},
        ],
        "instance_type": "t3.medium",
    }

    observation = ResourceObserver().observe(provider, "ec2", "i-normalized-1")

    assert observation.provider == "aws"
    assert observation.resource_type == "ec2"
    assert observation.resource_id == "i-normalized-1"
    assert observation.data["state"] == "running"
    assert observation.data["health"] == "healthy"
    assert observation.data["tags"] == {
        "Environment": "prod",
        "Team": "platform",
    }
    assert observation.data["metadata"]["instance_type"] == "t3.medium"
    assert observation.as_dict()["read_only"] is True


def test_resource_observer_defaults_missing_state_health_and_tags():
    from autonomy.aws_provider import AWSProvider
    from autonomy.resource_observer import ResourceObserver

    class FakeAWSService:
        def get_ec2_instances(self, state=None, tag_filter=None):
            return {}

        def get_ec2_summary(self):
            return {}

        def get_s3_buckets(self):
            return {}

    provider = AWSProvider(FakeAWSService())
    provider.get_resource = lambda resource_type, resource_id: {
        "provider": "aws",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "read_only": True,
    }

    observation = ResourceObserver().observe(provider, "ec2", "i-normalized-2")

    assert observation.data["state"] == "unknown"
    assert observation.data["health"] == "unknown"
    assert observation.data["tags"] == {}
    assert observation.data["metadata"] == {}


def test_resource_observer_rejects_empty_resource_identity():
    from autonomy.aws_provider import AWSProvider
    from autonomy.resource_observer import ResourceObserver

    provider = AWSProvider(object())
    observer = ResourceObserver()

    try:
        observer.observe(provider, "", "resource-1")
        assert False
    except ValueError as exc:
        assert str(exc) == "resource_type cannot be empty"

    try:
        observer.observe(provider, "ec2", "")
        assert False
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
