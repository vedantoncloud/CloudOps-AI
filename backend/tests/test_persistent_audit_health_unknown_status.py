import sqlite3

from autonomy.persistent_audit_health import PersistentAuditHealthChecker


def test_health_reports_unknown_status_as_inconsistent(tmp_path):
    database = tmp_path / "unknown-status.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE audit_idempotency (
                run_id TEXT,
                event_type TEXT,
                evidence_json TEXT,
                status TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO audit_idempotency VALUES (?, ?, ?, ?)",
            ("run-1", "event-1", "{}", "unexpected"),
        )

    health = PersistentAuditHealthChecker(database).inspect()

    assert health.total_claims == 1
    assert health.pending_claims == 0
    assert health.emitted_claims == 0
    assert health.evidence["consistent"] is False
    assert health.evidence["unknown_status_claims"] == 1
