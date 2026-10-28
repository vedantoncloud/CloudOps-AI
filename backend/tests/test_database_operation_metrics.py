import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_trail import PersistentAuditTrail
from main import database_operation_failures
from observability import database_operation_metrics, observed_sqlite_connection


def _entry(operation):
    return next(
        item
        for item in database_operation_metrics.failure_snapshot()["operations"]
        if item["operation"] == operation
    )


def test_sqlite_close_failure_is_counted_and_propagated():
    class CloseFailure:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def close(self):
            raise sqlite3.OperationalError("private close diagnostic")

    with observed_sqlite_connection(lambda: sqlite3.connect(":memory:"), "close_failure_probe"):
        pass
    before = _entry("close_failure_probe").copy()
    try:
        with observed_sqlite_connection(CloseFailure, "close_failure_probe"):
            pass
    except sqlite3.OperationalError as exc:
        assert "private close diagnostic" in str(exc)
    else:
        raise AssertionError("SQLite close failure should propagate")

    after = _entry("close_failure_probe")
    assert after["calls"] == before["calls"] + 1
    assert after["failures"] == before["failures"] + 1

def test_audit_store_success_and_sqlite_failure_are_counted_safely(tmp_path: Path):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    before = _entry("audit_events").copy()
    trail.get_events()
    after_success = _entry("audit_events")
    assert after_success["calls"] == before["calls"] + 1
    assert after_success["failures"] == before["failures"]

    def fail_connection():
        raise sqlite3.OperationalError("private path and SQL details")

    trail._connect = fail_connection
    try:
        trail.get_events()
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("SQLite failure should propagate to the caller")

    after_failure = _entry("audit_events")
    assert after_failure["calls"] == after_success["calls"] + 1
    assert after_failure["failures"] == after_success["failures"] + 1
    assert "private path" not in str(database_operation_metrics.failure_snapshot())


def test_invalid_audit_input_does_not_count_as_database_failure(tmp_path: Path):
    trail = PersistentAuditTrail(tmp_path / "audit.db")
    before = _entry("audit_events").copy()
    try:
        trail.record(action_id="", action_type="stop", resource_type="ec2", resource_id="i-1",
                     old_status="running", new_status="stopped", event="planned")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid audit input should be rejected")
    assert _entry("audit_events") == before


def test_idempotency_store_counts_success_and_database_failure(tmp_path: Path):
    store = PersistentAuditIdempotencyStore(tmp_path / "idempotency.db")
    before = _entry("audit_idempotency").copy()
    claim = store.claim("run-1", "completed", {"ok": True})
    assert claim.emitted
    after_success = _entry("audit_idempotency")
    assert after_success["calls"] == before["calls"] + 1
    assert after_success["failures"] == before["failures"]

    def fail_connection():
        raise sqlite3.OperationalError("sensitive store diagnostic")

    store._connect = fail_connection
    try:
        store.contains("run-1", "completed")
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("SQLite failure should propagate to the caller")
    after_failure = _entry("audit_idempotency")
    assert after_failure["calls"] == after_success["calls"] + 1
    assert after_failure["failures"] == after_success["failures"] + 1
    assert "sensitive store diagnostic" not in str(database_operation_metrics.failure_snapshot())


def test_database_operation_summary_is_admin_only_and_sanitized():
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={
            "reader": Principal("reader", "reader", "tenant"),
            "admin": Principal("admin", "admin", "tenant"),
        },
    )
    app.add_api_route("/operations/database-failures", database_operation_failures)
    client = TestClient(app)

    assert client.get(
        "/operations/database-failures", headers={"Authorization": "Bearer reader"}
    ).status_code == 403
    response = client.get(
        "/operations/database-failures", headers={"Authorization": "Bearer admin"}
    )
    assert response.status_code == 200
    assert response.json()["scope"] == "since_process_start"
    assert {item["operation"] for item in response.json()["operations"]} <= {
        "audit_events", "audit_idempotency"
    }
    assert "database_path" not in response.text
