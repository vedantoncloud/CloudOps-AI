from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


def test_health_reports_read_only_sqlite_inspection(tmp_path):
    database = tmp_path / "readonly-audit.db"
    PersistentAuditIdempotencyStore(database)

    health = PersistentAuditHealthChecker(database).inspect()

    assert health.evidence["store"] == "sqlite"
    assert health.evidence["read_only"] is True
    assert health.evidence["consistent"] is True
