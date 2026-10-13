from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit_api import audit_trail, router


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_integrity_endpoint_reports_empty_trail_as_valid():
    audit_trail.clear()

    response = make_client().get("/autonomy/audit/integrity")

    assert response.status_code == 200
    assert response.json() == {
        "valid": True, "event_count": 0, "first_invalid_index": None
    }


def test_integrity_endpoint_reports_recorded_event_count():
    audit_trail.clear()
    for index in range(2):
        audit_trail.record(
            action_id=f"action-{index}",
            action_type="scale",
            resource_type="instance",
            resource_id=f"i-{index}",
            old_status="running",
            new_status="stopped",
            event="action_completed",
        )

    response = make_client().get("/autonomy/audit/integrity")

    assert response.status_code == 200
    assert response.json() == {
        "valid": True, "event_count": 2, "first_invalid_index": None
    }


def test_integrity_endpoint_detects_event_tampering():
    audit_trail.clear()
    recorded = audit_trail.record(
        action_id="action-1",
        action_type="scale",
        resource_type="instance",
        resource_id="i-123",
        old_status="running",
        new_status="stopped",
        event="action_completed",
    )

    recorded.details["tampered"] = True

    response = make_client().get("/autonomy/audit/integrity")

    assert response.status_code == 200
    assert response.json() == {
        "valid": False, "event_count": 1, "first_invalid_index": 0
    }


def test_integrity_endpoint_does_not_modify_audit_events():
    audit_trail.clear()
    audit_trail.record(
        action_id="action-1",
        action_type="scale",
        resource_type="instance",
        resource_id="i-123",
        old_status="running",
        new_status="stopped",
        event="action_completed",
    )

    before = audit_trail.get_events()
    response = make_client().get("/autonomy/audit/integrity")

    assert response.status_code == 200
    assert audit_trail.get_events() == before

def test_integrity_endpoint_uses_atomic_snapshot(monkeypatch):
    audit_trail.clear()
    calls = []

    def snapshot():
        calls.append(True)
        from autonomy.audit import AuditIntegrityResult

        return AuditIntegrityResult(True, 7, None)

    monkeypatch.setattr(audit_trail, "get_integrity_diagnostics", snapshot)

    response = make_client().get("/autonomy/audit/integrity")

    assert response.status_code == 200
    assert response.json() == {
        "valid": True, "event_count": 7, "first_invalid_index": None
    }
    assert calls == [True]

