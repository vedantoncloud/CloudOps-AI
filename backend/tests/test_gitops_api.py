from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.gitops import GitOpsChange, GitOpsEngine
from autonomy.gitops_api import registry, router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def make_change_set(*, requires_approval=True):
    return GitOpsEngine().create_change_set(
        source_action_id="action-api",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id="i-api-123",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="Resize instance",
            )
        ],
        requires_approval=requires_approval,
    )


def setup_function():
    registry.clear()


def test_list_changes_starts_empty():
    client = TestClient(make_app())

    response = client.get("/autonomy/gitops/changes")

    assert response.status_code == 200
    assert response.json() == []


def test_get_missing_change_returns_404():
    client = TestClient(make_app())

    response = client.get(
        "/autonomy/gitops/changes/missing-change"
    )

    assert response.status_code == 404


def test_registered_change_can_be_fetched():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.get(
        f"/autonomy/gitops/changes/{change_set.change_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["change_id"] == change_set.change_id
    assert data["source_action_id"] == "action-api"
    assert data["status"] == "pending_approval"
    assert data["change_count"] == 1


def test_list_changes_returns_registered_changes():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.get("/autonomy/gitops/changes")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_pending_endpoint_returns_pending_changes():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.get(
        "/autonomy/gitops/changes/pending"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["change_id"] == change_set.change_id


def test_approve_endpoint_changes_status():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "operator",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "approved"
    assert data["approved_by"] == "operator"


def test_approve_missing_change_returns_404():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/gitops/changes/missing/approve",
        json={
            "approved_by": "operator",
        },
    )

    assert response.status_code == 404


def test_approve_empty_user_returns_422():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "",
        },
    )

    assert response.status_code == 422


def test_reject_endpoint_changes_status():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/reject",
        json={
            "rejected_by": "operator",
            "reason": "Risk too high",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "rejected"
    assert data["metadata"]["rejected_by"] == "operator"
    assert data["metadata"]["rejection_reason"] == "Risk too high"


def test_reject_missing_change_returns_404():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/gitops/changes/missing/reject",
        json={
            "rejected_by": "operator",
            "reason": "Risk too high",
        },
    )

    assert response.status_code == 404


def test_apply_before_approval_is_blocked():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/apply",
        json={
            "dry_run": True,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is False
    assert data["status"] == "pending_approval"


def test_approved_change_can_be_dry_run_applied():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    approved = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "operator",
        },
    )

    assert approved.status_code == 200

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/apply",
        json={
            "dry_run": True,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["status"] == "applied"
    assert data["applied_changes"] == 1


def test_real_apply_is_rejected():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "operator",
        },
    )

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/apply",
        json={
            "dry_run": False,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is False
    assert data["dry_run"] is False
    assert data["status"] == "failed"


def test_verify_after_dry_run_succeeds():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "operator",
        },
    )

    applied = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/apply",
        json={
            "dry_run": True,
        },
    )

    assert applied.json()["success"] is True

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/verify",
        json={
            "observed_values": {
                "ec2/i-api-123/instance_type": "t3.large",
            }
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["verified"] is True
    assert data["status"] == "verified"


def test_verify_failure_is_reported():
    change_set = make_change_set()
    registry.register(change_set)

    client = TestClient(make_app())

    client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/approve",
        json={
            "approved_by": "operator",
        },
    )

    client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/apply",
        json={
            "dry_run": True,
        },
    )

    response = client.post(
        f"/autonomy/gitops/changes/{change_set.change_id}/verify",
        json={
            "observed_values": {
                "ec2/i-api-123/instance_type": "t3.medium",
            }
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["verified"] is False
    assert data["status"] == "failed"


def test_verify_missing_change_returns_404():
    client = TestClient(make_app())

    response = client.post(
        "/autonomy/gitops/changes/missing/verify",
        json={
            "observed_values": {},
        },
    )

    assert response.status_code == 404
