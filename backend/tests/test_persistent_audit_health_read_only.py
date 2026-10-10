from autonomy.persistent_audit_health import PersistentAuditHealthChecker

def test_inspect_does_not_create_missing_database(tmp_path):
    database = tmp_path / "missing.db"

    try:
        PersistentAuditHealthChecker(database).inspect()
    except ValueError:
        pass
    else:
        raise AssertionError("Expected missing store to raise ValueError")

    assert not database.exists()


def test_list_pending_does_not_create_missing_database(tmp_path):
    database = tmp_path / "missing-pending.db"

    try:
        PersistentAuditHealthChecker(database).list_pending()
    except ValueError:
        pass
    else:
        raise AssertionError("Expected missing store to raise ValueError")

    assert not database.exists()


def test_health_checker_supports_special_characters_in_database_path(tmp_path):
    from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore

    database = tmp_path / "audit #1 test.db"
    store = PersistentAuditIdempotencyStore(database)
    store.claim("run-special", "event-special", {"source": "path-test"})

    checker = PersistentAuditHealthChecker(database)

    health = checker.inspect()
    pending = checker.list_pending()

    assert health.total_claims == 1
    assert health.pending_claims == 1
    assert len(pending) == 1
    assert pending[0]["run_id"] == "run-special"


def test_inspect_detects_malformed_evidence_json(tmp_path):
    from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
    import sqlite3

    database = tmp_path / "malformed-evidence.db"
    store = PersistentAuditIdempotencyStore(database)
    store.claim("run-malformed", "event-malformed", {"source": "valid"})

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_idempotency SET evidence_json = ? WHERE run_id = ?",
            ("{not-valid-json", "run-malformed"),
        )
        connection.commit()

    health = PersistentAuditHealthChecker(database).inspect()

    assert health.evidence["malformed_evidence_claims"] == 1
    assert health.evidence["consistent"] is True
