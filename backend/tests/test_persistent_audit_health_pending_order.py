from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_audit_records_are_sorted_deterministically(tmp_path):
    database = tmp_path / "pending-order.db"
    store = PersistentAuditIdempotencyStore(database)

    store.claim("run-z", "event-b", {"source": "test"})
    store.claim("run-a", "event-z", {"source": "test"})
    store.claim("run-a", "event-a", {"source": "test"})

    pending = PersistentAuditHealthChecker(database).list_pending()

    assert [
        (item["run_id"], item["event_type"])
        for item in pending
    ] == [
        ("run-a", "event-a"),
        ("run-a", "event-z"),
        ("run-z", "event-b"),
    ]
