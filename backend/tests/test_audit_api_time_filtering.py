import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.audit import AuditEvent
from autonomy.audit_api import audit_trail, router


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def controlled_events(monkeypatch):
    audit_trail.clear()
    events = [
        AuditEvent("a", "control_loop", "ec2", "i-1", "old", "new", "change", "2024-01-01T00:00:00+00:00", {"n": 1}),
        AuditEvent("b", "control_loop", "ec2", "i-2", "old", "new", "change", "2024-01-02T12:00:00+00:00", {"n": 2}),
        AuditEvent("c", "gitops", "s3", "bucket", "old", "new", "created", "2024-01-03T00:00:00+00:00", {"n": 3}),
    ]

    def get_events(action_id=None):
        return [item for item in events if action_id is None or item.action_id == action_id]

    monkeypatch.setattr(audit_trail, "get_events", get_events)
    yield
    audit_trail.clear()


def ids(response):
    return [item["action_id"] for item in response.json()]


def test_start_and_end_bounds_are_inclusive():
    client = make_client()
    assert ids(client.get("/autonomy/audit/events", params={"start_time": "2024-01-02T12:00:00Z"})) == ["b", "c"]
    assert ids(client.get("/autonomy/audit/events", params={"end_time": "2024-01-02T12:00:00Z"})) == ["a", "b"]


def test_combined_time_range_and_timezone_offset():
    response = make_client().get("/autonomy/audit/events", params={
        "start_time": "2024-01-02T14:00:00+02:00",
        "end_time": "2024-01-03T02:00:00+02:00",
    })
    assert ids(response) == ["b", "c"]


def test_naive_query_timestamps_are_treated_as_utc():
    response = make_client().get("/autonomy/audit/events", params={
        "start_time": "2024-01-02T12:00:00",
        "end_time": "2024-01-02T12:00:00",
    })
    assert ids(response) == ["b"]


@pytest.mark.parametrize("endpoint", ["/autonomy/audit/events", "/autonomy/audit/events/export"])
def test_invalid_and_reversed_ranges_return_422(endpoint):
    client = make_client()
    assert client.get(endpoint, params={"start_time": "not-a-date"}).status_code == 422
    assert client.get(endpoint, params={
        "start_time": "2024-01-03T00:00:00Z", "end_time": "2024-01-01T00:00:00Z",
    }).status_code == 422


def test_list_export_parity_with_time_filters():
    client = make_client()
    params = {"start_time": "2024-01-02T00:00:00Z", "end_time": "2024-01-03T00:00:00Z"}
    listed = client.get("/autonomy/audit/events", params=params)
    exported = client.get("/autonomy/audit/events/export", params=params)
    assert listed.status_code == exported.status_code == 200
    assert listed.json() == [json.loads(line) for line in exported.text.splitlines()]


def test_time_filter_combines_with_existing_filters_and_pagination():
    response = make_client().get("/autonomy/audit/events", params={
        "start_time": "2024-01-01T00:00:00Z", "end_time": "2024-01-03T00:00:00Z",
        "action_type": "control_loop", "resource_type": "ec2", "offset": 1, "limit": 1,
    })
    assert ids(response) == ["b"]


def test_no_time_filters_preserve_legacy_behavior():
    assert ids(make_client().get("/autonomy/audit/events")) == ["a", "b", "c"]
