from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_reports_consistent_empty_database(tmp_path):
    database = tmp_path / "empty-audit.db"
    PersistentAuditIdempotencyStore(database)

    health = PersistentAuditHealthChecker(database).inspect()

    assert health.total_claims == 0
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is True
