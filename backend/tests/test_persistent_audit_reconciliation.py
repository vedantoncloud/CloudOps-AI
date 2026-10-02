from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


def _seed_store(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    store.claim(
        "run-a",
        "recovery_completed",
        {"run_id": "run-a", "action_id": "action-a"},
    )
    store.claim(
        "run-b",
        "recovery_failed",
        {"run_id": "run-b", "action_id": "action-b"},
    )
    return store


def _set_claim_times(store, monkeypatch, times):
    original = store.path

    class FakeHealthChecker:
        def __init__(self, path):
            self.path = path

        def list_pending(self):
            return [
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "claimed_at": timestamp,
                    "evidence": evidence,
                }
                for run_id, event_type, timestamp, evidence in times
            ]

    monkeypatch.setattr(
        "autonomy.persistent_audit_reconciliation.PersistentAuditHealthChecker",
        FakeHealthChecker,
    )
    return original


def test_reconciliation_is_read_only_and_deterministic(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    _set_claim_times(
        store,
        monkeypatch,
        [
            ("run-a", "recovery_completed", now.timestamp() - 10, {"a": 1}),
            ("run-b", "recovery_failed", now.timestamp() - 20, {"b": 2}),
        ],
    )

    before = store.contains("run-a", "recovery_completed")
    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()
    after = store.contains("run-a", "recovery_completed")

    assert result.count == 2
    assert result.active_count == 2
    assert result.stale_count == 0
    assert [item.run_id for item in result.items] == ["run-a", "run-b"]
    assert result.evidence["read_only"] is True
    assert before is True
    assert after is True


def test_stale_claim_is_classified_without_mutation(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    _set_claim_times(
        store,
        monkeypatch,
        [
            ("run-a", "recovery_completed", now.timestamp() - 301, {}),
            ("run-b", "recovery_failed", now.timestamp() - 10, {}),
        ],
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()

    assert result.stale_count == 1
    assert result.active_count == 1
    assert result.items[0].status == "stale"
    assert result.items[1].status == "active"


def test_lease_boundary_is_stale(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    _set_claim_times(
        store,
        monkeypatch,
        [
            ("run-a", "recovery_completed", now.timestamp() - 300, {}),
            ("run-b", "recovery_failed", now.timestamp() - 300, {}),
        ],
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()

    assert result.stale_count == 2
    assert result.active_count == 0


def test_missing_run_id_is_rejected(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    _set_claim_times(
        store,
        monkeypatch,
        [("", "recovery_completed", 1, {})],
    )

    with pytest.raises(ValueError, match="run_id"):
        PersistentAuditReconciliation(store).inspect()


def test_missing_event_type_is_rejected(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    _set_claim_times(
        store,
        monkeypatch,
        [("run-a", "", 1, {})],
    )

    with pytest.raises(ValueError, match="event_type"):
        PersistentAuditReconciliation(store).inspect()


def test_invalid_claimed_at_is_rejected(tmp_path, monkeypatch):
    store = _seed_store(tmp_path)
    _set_claim_times(
        store,
        monkeypatch,
        [("run-a", "recovery_completed", "not-a-timestamp", {})],
    )

    with pytest.raises(ValueError, match="invalid claimed_at"):
        PersistentAuditReconciliation(store).inspect()


def test_negative_lease_is_rejected(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")

    with pytest.raises(ValueError, match="lease_seconds"):
        PersistentAuditReconciliation(store, lease_seconds=-1)


def test_empty_store_returns_empty_result(tmp_path):
    store = PersistentAuditIdempotencyStore(tmp_path / "audit.db")
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    result = PersistentAuditReconciliation(store, now=now).inspect()

    assert result.items == ()
    assert result.count == 0
    assert result.active_count == 0
    assert result.stale_count == 0
    assert result.evidence["read_only"] is True


@pytest.mark.parametrize(
    "malformed_evidence",
    [
        ["unexpected", "list"],
        "unexpected-string",
        42,
        None,
    ],
)
def test_non_object_evidence_is_preserved_as_raw_value(
    tmp_path, monkeypatch, malformed_evidence
):
    store = _seed_store(tmp_path)
    now = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)

    _set_claim_times(
        store,
        monkeypatch,
        [
            (
                "run-a",
                "recovery_completed",
                now.timestamp() - 10,
                malformed_evidence,
            )
        ],
    )

    result = PersistentAuditReconciliation(
        store,
        lease_seconds=300,
        now=now,
    ).inspect()

    assert result.count == 1
    assert result.items[0].evidence == {"raw": malformed_evidence}
    assert result.evidence["read_only"] is True
