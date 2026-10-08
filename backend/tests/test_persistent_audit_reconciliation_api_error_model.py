from __future__ import annotations

import pytest
from pydantic import ValidationError

from autonomy.persistent_audit_reconciliation_api import (
    AuditReconciliationErrorResponse,
)


def test_reconciliation_error_requires_non_empty_detail():
    with pytest.raises(ValidationError):
        AuditReconciliationErrorResponse(detail="")


def test_reconciliation_error_accepts_meaningful_detail():
    response = AuditReconciliationErrorResponse(
        detail="Persistent audit reconciliation is unavailable"
    )

    assert response.detail == "Persistent audit reconciliation is unavailable"
