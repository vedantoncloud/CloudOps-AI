import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


@pytest.mark.parametrize(
    ("run_id", "event_type", "expected_error"),
    [
        (" ", "reconciliation", "run_id is required"),
        ("run-validation", " ", "event_type is required"),
    ],
)
def test_mark_emitted_rejects_whitespace_identifiers(
    tmp_path,
    run_id,
    event_type,
    expected_error,
):
    store = PersistentAuditIdempotencyStore(tmp_path / "whitespace-identifiers.db")

    with pytest.raises(ValueError, match=expected_error):
        store.mark_emitted(run_id, event_type, "valid-token")
