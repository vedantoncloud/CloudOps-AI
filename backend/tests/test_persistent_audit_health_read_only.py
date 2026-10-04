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
