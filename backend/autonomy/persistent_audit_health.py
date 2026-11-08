from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True)
class PersistentAuditHealth:
    path: str
    total_claims: int
    pending_claims: int
    emitted_claims: int
    evidence_conflicts: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


class PersistentAuditHealthChecker:
    """Read-only health inspection for SQLite or an explicitly shared SQL store."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.backend = "sqlalchemy" if "://" in self.path else "sqlite"
        # Never return a database URL (which may contain credentials) from an API.
        self.display_path = "shared-database" if self.backend == "sqlalchemy" else self.path

    def _shared_query(self, statement: str, params: dict[str, Any] | None = None):
        engine = create_engine(self.path, pool_pre_ping=True, future=True)
        try:
            with engine.connect() as connection:
                return connection.execute(text(statement), params or {}).all()
        finally:
            engine.dispose()

    def inspect(self) -> PersistentAuditHealth:
        if self.backend == "sqlalchemy":
            try:
                row = self._shared_query(
                    """
                    SELECT
                        COUNT(*) AS total_claims,
                        COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN status = 'emitted' THEN 1 ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN status NOT IN ('pending', 'emitted')
                                          THEN 1 ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN evidence_json IS NULL
                                          OR JSON_VALID(evidence_json) = 0
                                          THEN 1 ELSE 0 END), 0)
                    FROM audit_idempotency
                    """
                )[0]
            except SQLAlchemyError as exc:
                raise ValueError("Persistent audit idempotency store is not initialized") from exc
            total, pending, emitted, unknown, malformed_evidence = (
                int(value or 0) for value in row
            )
            return PersistentAuditHealth(
                path=self.display_path,
                total_claims=total,
                pending_claims=pending,
                emitted_claims=emitted,
                evidence={
                    "store": "mysql" if self.path.startswith("mysql") else "sqlite",
                    "read_only": True,
                    "consistent": total == pending + emitted and unknown == 0 and malformed_evidence == 0,
                    "unknown_status_claims": unknown,
                    "malformed_evidence_claims": malformed_evidence,
                },
            )

        connection = None
        try:
            connection = sqlite3.connect(
                f"{Path(self.path).resolve().as_uri()}?mode=ro", uri=True
            )
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_claims,
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status = 'emitted' THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status NOT IN ('pending', 'emitted')
                                      THEN 1 ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN evidence_json IS NULL
                                      OR json_valid(evidence_json) = 0
                                      THEN 1 ELSE 0 END), 0)
                FROM audit_idempotency
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise ValueError("Persistent audit idempotency store is not initialized") from exc
        finally:
            if connection is not None:
                connection.close()

        total, pending, emitted, unknown, malformed_evidence = (
            int(value or 0) for value in row
        )
        return PersistentAuditHealth(
            path=self.display_path,
            total_claims=total,
            pending_claims=pending,
            emitted_claims=emitted,
            evidence={
                "store": "sqlite",
                "read_only": True,
                "consistent": total == pending + emitted and unknown == 0 and malformed_evidence == 0,
                "unknown_status_claims": unknown,
                "malformed_evidence_claims": malformed_evidence,
            },
        )

    def list_pending(self) -> list[dict[str, Any]]:
        if self.backend == "sqlalchemy":
            try:
                rows = self._shared_query(
                    """
                    SELECT run_id, event_type, evidence_json, claimed_at
                    FROM audit_idempotency
                    WHERE status = 'pending'
                    ORDER BY run_id ASC, event_type ASC
                    """
                )
            except SQLAlchemyError as exc:
                raise ValueError("Persistent audit idempotency store is not initialized") from exc
            result = []
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

        connection = None
        try:
            connection = sqlite3.connect(
                f"{Path(self.path).resolve().as_uri()}?mode=ro", uri=True
            )
            rows = connection.execute(
                """
                SELECT run_id, event_type, evidence_json, claimed_at
                FROM audit_idempotency
                WHERE status = 'pending'
                ORDER BY run_id ASC, event_type ASC
                """
            ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError("Persistent audit idempotency store is not initialized") from exc
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
