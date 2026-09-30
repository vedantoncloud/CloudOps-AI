"""Stable serialization helpers for governance reports."""

from __future__ import annotations

import json
from typing import Any


def serialize_governance_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe, deterministically ordered governance report."""
    return json.loads(
        json.dumps(
            report,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
    )
