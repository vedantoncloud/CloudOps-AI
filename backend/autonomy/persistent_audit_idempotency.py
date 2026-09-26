from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PersistentAuditClaim:
    run_id: str
    event_type: str
    emitted: bool
    evidence: dict[str, Any]


class PersistentAuditIdempotencyStore:
    """Small SQLite-backed claim store for cross-process audit idempotency."""

    def __init__(self, path: str | Path = "cloudops_audit_idempotency.db") -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_idempotency (
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, event_type)
                )
                """
            )

    @staticmethod
    def _normalize_evidence(evidence: dict[str, Any]) -> str:
        return json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def claim(
        self,
        run_id: str,
        event_type: str,
        evidence: dict[str, Any],
    ) -> PersistentAuditClaim:
        run_id = (run_id or "").strip()
        event_type = (event_type or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        if not event_type:
            raise ValueError("event_type is required")

        normalized = self._normalize_evidence(evidence)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT evidence_json
                FROM audit_idempotency
                WHERE run_id = ? AND event_type = ?
                """,
                (run_id, event_type),
            ).fetchone()

            if row is not None:
                previous = json.loads(row[0])
                if previous != json.loads(normalized):
                    raise ValueError("Conflicting audit evidence")
                return PersistentAuditClaim(
                    run_id, event_type, False, dict(evidence)
                )

            connection.execute(
                """
                INSERT INTO audit_idempotency(run_id, event_type, evidence_json)
                VALUES (?, ?, ?)
                """,
                (run_id, event_type, normalized),
            )

        return PersistentAuditClaim(run_id, event_type, True, dict(evidence))

    def contains(self, run_id: str, event_type: str) -> bool:
        run_id = (run_id or "").strip()
        event_type = (event_type or "").strip()
        if not run_id or not event_type:
            return False

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM audit_idempotency
                WHERE run_id = ? AND event_type = ?
                """,
                (run_id, event_type),
            ).fetchone()
        return row is not None

    def close(self) -> None:
        """Compatibility hook; connections are intentionally short-lived."""
        return None
