from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_empty_store_health_reports_zero_claims(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    health = PersistentAuditHealthChecker(store.path).inspect()

    assert health.total_claims == 0
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["malformed_evidence_claims"] == 0
    assert health.evidence["consistent"] is True
    assert health.evidence["read_only"] is True
