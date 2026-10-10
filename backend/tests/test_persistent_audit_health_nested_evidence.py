from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_pending_listing_preserves_nested_evidence(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    evidence = {
        "action_id": "action-42",
        "metadata": {"source": "cloudops-ai", "attempt": 2},
        "checks": ["identity", "permissions"],
    }

    store.claim("run-evidence", "recovery_completed", evidence)

    pending = PersistentAuditHealthChecker(store.path).list_pending()

    assert len(pending) == 1
    assert pending[0]["evidence"] == evidence
