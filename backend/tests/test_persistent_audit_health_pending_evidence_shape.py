from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_audit_evidence_is_returned_as_dictionary(tmp_path):
    database = tmp_path / "pending-evidence.db"
    store = PersistentAuditIdempotencyStore(database)
    evidence = {
        "source": "cloudops-ai",
        "attempt": 3,
        "details": {"status": "pending"},
    }

    store.claim("run-evidence", "reconciliation", evidence)

    pending = PersistentAuditHealthChecker(database).list_pending()

    assert len(pending) == 1
    assert pending[0]["run_id"] == "run-evidence"
    assert pending[0]["event_type"] == "reconciliation"
    assert pending[0]["evidence"] == evidence
