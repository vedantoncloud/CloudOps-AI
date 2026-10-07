from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomy.persistent_audit_reconciliation_api import (
    AuditReconciliationEvidence,
    AuditReconciliationItemResponse,
    AuditReconciliationResponse,
)


def _item():
    return AuditReconciliationItemResponse(
        run_id="run-1",
        event_type="recovery_completed",
        status="active",
        claimed_at=100.0,
        age_seconds=10.0,
        evidence={"source": "test"},
    )


def _evidence():
    return AuditReconciliationEvidence(
        store="sqlite",
        read_only=True,
        lease_seconds=300.0,
        pending_count=1,
        active_count=1,
        stale_count=0,
    )


def _response(**overrides):
    values = {
        "count": 1,
        "active_count": 1,
        "stale_count": 0,
        "items": [_item()],
        "evidence": _evidence(),
        "read_only": True,
    }
    values.update(overrides)
    return AuditReconciliationResponse(**values)


def test_reconciliation_response_rejects_negative_counts():
    with pytest.raises(ValidationError):
        _response(count=-1)


def test_reconciliation_response_rejects_count_item_mismatch():
    with pytest.raises(ValidationError):
        _response(count=2)


def test_reconciliation_response_rejects_active_stale_mismatch():
    with pytest.raises(ValidationError):
        _response(active_count=0, stale_count=0)


def test_reconciliation_evidence_rejects_count_mismatch():
    with pytest.raises(ValidationError):
        AuditReconciliationEvidence(
            store="sqlite",
            read_only=True,
            lease_seconds=300.0,
            pending_count=2,
            active_count=1,
            stale_count=0,
        )


def test_reconciliation_item_rejects_negative_claimed_at():
    with pytest.raises(ValidationError):
        AuditReconciliationItemResponse(
            run_id="run-1",
            event_type="recovery_completed",
            status="active",
            claimed_at=-1.0,
            age_seconds=10.0,
            evidence={},
        )


def test_reconciliation_item_rejects_negative_age():
    with pytest.raises(ValidationError):
        AuditReconciliationItemResponse(
            run_id="run-1",
            event_type="recovery_completed",
            status="active",
            claimed_at=100.0,
            age_seconds=-1.0,
            evidence={},
        )


def test_reconciliation_response_accepts_valid_contract():
    response = _response()

    assert response.count == 1
    assert response.active_count == 1
    assert response.stale_count == 0
    assert len(response.items) == 1
    assert response.read_only is True

def test_reconciliation_item_rejects_unknown_status():
    with pytest.raises(ValidationError):
        AuditReconciliationItemResponse(
            run_id="run-1",
            event_type="event",
            status="unknown",
            claimed_at=100.0,
            age_seconds=10.0,
            evidence={},
        )
