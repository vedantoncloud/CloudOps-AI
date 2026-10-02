from __future__ import annotations

import pytest

from autonomy.persistent_audit_health import PersistentAuditHealthChecker


def test_missing_database_directory_is_reported_as_value_error(tmp_path):
    db_path = tmp_path / "missing" / "audit.db"
    checker = PersistentAuditHealthChecker(db_path)

    with pytest.raises(
        ValueError,
        match="Persistent audit idempotency store is not initialized",
    ):
        checker.list_pending()


def test_corrupt_database_is_reported_as_value_error(tmp_path):
    db_path = tmp_path / "corrupt.db"
    db_path.write_bytes(b"not a valid sqlite database")

    checker = PersistentAuditHealthChecker(db_path)

    with pytest.raises(
        ValueError,
        match="Persistent audit idempotency store is not initialized",
    ):
        checker.list_pending()
