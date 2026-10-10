from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_claims_are_ordered_by_run_and_event(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    store.claim("run-b", "recovery_completed", {"id": "b"})
    store.claim("run-a", "recovery_failed", {"id": "c"})
    store.claim("run-a", "recovery_completed", {"id": "a"})

    pending = PersistentAuditHealthChecker(store.path).list_pending()

    assert [(item["run_id"], item["event_type"]) for item in pending] == [
        ("run-a", "recovery_completed"),
        ("run-a", "recovery_failed"),
        ("run-b", "recovery_completed"),
    ]
