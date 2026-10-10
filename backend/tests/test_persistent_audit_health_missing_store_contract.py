import pytest

from autonomy.persistent_audit_health import PersistentAuditHealthChecker


def test_health_inspection_rejects_missing_store(tmp_path):
    missing_path = tmp_path / "missing-audit.db"

    with pytest.raises(
        ValueError,
        match="Persistent audit idempotency store is not initialized",
    ):
        PersistentAuditHealthChecker(missing_path).inspect()

    assert not missing_path.exists()
