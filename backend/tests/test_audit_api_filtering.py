from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit_api import audit_trail, router


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def seed_events():
    audit_trail.clear()

    audit_trail.record(
        action_id="action-a",
        action_type="control_loop",
        resource_type="ec2",
        resource_id="i-001",
        old_status="pending",
        new_status="review",
        event="governance_review",
        details={"sequence": 1},
        actor_id="operator-1",
    )
    audit_trail.record(
        action_id="action-b",
        action_type="control_loop",
        resource_type="ec2",
        resource_id="i-002",
        old_status="pending",
        new_status="blocked",
        event="control_loop_blocked",
        details={"sequence": 2},
        actor_id="operator-2",
    )
    audit_trail.record(
        action_id="action-c",
        action_type="gitops_change",
        resource_type="s3",
        resource_id="bucket-001",
        old_status="pending",
        new_status="approved",
        event="gitops_approved",
        details={"sequence": 3},
        actor_id="operator-1",
    )


def test_audit_api_filters_by_resource_id():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={"resource_id": "i-002"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action_id"] == "action-b"


def test_audit_api_filters_by_event():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={"event": "gitops_approved"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["resource_id"] == "bucket-001"


def test_audit_api_filters_by_action_type():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={"action_type": "control_loop"},
    )

    assert response.status_code == 200
    assert [item["action_id"] for item in response.json()] == [
        "action-a",
        "action-b",
    ]


def test_audit_api_filters_by_action_id_and_current_status_before_pagination():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={"action_id": "action-c", "new_status": "approved", "limit": 1},
    )

    assert response.status_code == 200
    assert [item["action_id"] for item in response.json()] == ["action-c"]

    no_match = make_client().get(
        "/autonomy/audit/events", params={"new_status": "missing"}
    )
    assert no_match.status_code == 200
    assert no_match.json() == []


def test_audit_export_uses_current_status_filter():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events/export", params={"new_status": "blocked"}
    )

    assert response.status_code == 200
    assert response.json()["action_id"] == "action-b"
    assert response.headers["content-type"].startswith("application/x-ndjson")


def test_audit_api_supports_combined_filters():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={
            "action_type": "control_loop",
            "resource_id": "i-002",
            "event": "control_loop_blocked",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action_id"] == "action-b"


def test_audit_api_supports_limit_and_offset():
    seed_events()
    client = make_client()

    response = client.get(
        "/autonomy/audit/events",
        params={"offset": 1, "limit": 1},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action_id"] == "action-b"


def test_audit_api_preserves_unpaginated_legacy_response():
    seed_events()
    response = make_client().get("/autonomy/audit/events")

    assert response.status_code == 200
    assert [item["action_id"] for item in response.json()] == [
        "action-a",
        "action-b",
        "action-c",
    ]


def test_audit_api_rejects_invalid_pagination():
    client = make_client()

    assert client.get(
        "/autonomy/audit/events",
        params={"limit": 0},
    ).status_code == 422

    assert client.get(
        "/autonomy/audit/events",
        params={"offset": -1},
    ).status_code == 422

    assert client.get(
        "/autonomy/audit/events",
        params={"limit": 1001},
    ).status_code == 422

def test_audit_api_filters_by_resource_type():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={"resource_type": "s3"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["resource_id"] == "bucket-001"
    assert data[0]["resource_type"] == "s3"


def test_audit_api_combines_resource_type_with_existing_filters():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={
            "resource_type": "ec2",
            "action_type": "control_loop",
            "event": "control_loop_blocked",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["action_id"] == "action-b"


def test_audit_api_filters_by_actor_and_combines_with_existing_filters():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events",
        params={
            "actor_id": "operator-1",
            "resource_type": "ec2",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2030-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["action_id"] for item in data] == ["action-a"]
    assert data[0]["actor_id"] == "operator-1"

