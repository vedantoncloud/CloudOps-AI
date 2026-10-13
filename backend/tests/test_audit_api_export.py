import json

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
    )
    audit_trail.record(
        action_id="action-b",
        action_type="gitops_change",
        resource_type="s3",
        resource_id="bucket-001",
        old_status="pending",
        new_status="approved",
        event="gitops_approved",
        details={"sequence": 2},
    )


def test_audit_export_returns_newline_delimited_json():
    seed_events()
    response = make_client().get("/autonomy/audit/events/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert "audit-events.jsonl" in response.headers["content-disposition"]

    lines = response.text.splitlines()
    assert len(lines) == 2

    events = [json.loads(line) for line in lines]
    assert [item["action_id"] for item in events] == ["action-a", "action-b"]
    assert events[0]["details"] == {"sequence": 1}


def test_audit_export_applies_combined_filters():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events/export",
        params={
            "resource_type": "s3",
            "action_type": "gitops_change",
            "event": "gitops_approved",
        },
    )

    assert response.status_code == 200
    lines = response.text.splitlines()
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["action_id"] == "action-b"
    assert event["resource_id"] == "bucket-001"


def test_audit_export_returns_empty_body_when_no_events_match():
    seed_events()
    response = make_client().get(
        "/autonomy/audit/events/export",
        params={"resource_type": "rds"},
    )

    assert response.status_code == 200
    assert response.text == ""



def test_audit_listing_and_export_apply_identical_filters():
    seed_events()
    client = make_client()
    filters = {
        "resource_type": "ec2",
        "action_type": "control_loop",
    }

    listed = client.get("/autonomy/audit/events", params=filters)
    exported = client.get("/autonomy/audit/events/export", params=filters)

    assert listed.status_code == 200
    assert exported.status_code == 200

    listed_events = listed.json()
    exported_events = [
        json.loads(line) for line in exported.text.splitlines()
    ]

    assert listed_events == exported_events


def test_audit_listing_and_export_match_for_empty_results():
    seed_events()
    client = make_client()
    filters = {"resource_type": "rds"}

    listed = client.get("/autonomy/audit/events", params=filters)
    exported = client.get("/autonomy/audit/events/export", params=filters)

    assert listed.status_code == 200
    assert listed.json() == []
    assert exported.status_code == 200
    assert exported.text == ""
