from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PersistentAuditHealth:
    path: str
    total_claims: int
    pending_claims: int
    emitted_claims: int
    evidence_conflicts: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


class PersistentAuditHealthChecker:
    """Read-only health inspection for the persistent audit idempotency store."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def inspect(self) -> PersistentAuditHealth:
        connection = None
        try:
            connection = sqlite3.connect(f"{Path(self.path).resolve().as_uri()}?mode=ro", uri=True)
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_claims,
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'emitted' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(
                        CASE WHEN status NOT IN ('pending', 'emitted')
                        THEN 1 ELSE 0 END
                    ), 0)
                FROM audit_idempotency
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise ValueError(
                "Persistent audit idempotency store is not initialized"
            ) from exc
        finally:
            if connection is not None:
                connection.close()

        total, pending, emitted, unknown = (
            int(value or 0) for value in row
        )
        return PersistentAuditHealth(
            path=self.path,
            total_claims=total,
            pending_claims=pending,
            emitted_claims=emitted,
            evidence={
                "store": "sqlite",
                "read_only": True,
                "consistent": total == pending + emitted and unknown == 0,
                "unknown_status_claims": unknown,
            },
        )
    def list_pending(self) -> list[dict[str, Any]]:
        connection = None
        try:
            connection = sqlite3.connect(f"{Path(self.path).resolve().as_uri()}?mode=ro", uri=True)
            rows = connection.execute(
                """
                SELECT run_id, event_type, evidence_json, claimed_at
                FROM audit_idempotency
                WHERE status = 'pending'
                ORDER BY run_id ASC, event_type ASC
                """
            ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(
                "Persistent audit idempotency store is not initialized"
            ) from exc
        finally:
            if connection is not None:
                connection.close()

        result: list[dict[str, Any]] = []
        for run_id, event_type, evidence_json, claimed_at in rows:
            try:
                evidence = json.loads(evidence_json)
            except (TypeError, ValueError):
                evidence = {"raw": evidence_json}

            result.append(
                {
                    "run_id": run_id,
                    "event_type": event_type,
                    "claimed_at": float(claimed_at or 0),
                    "evidence": evidence,
                }
            )
        return result