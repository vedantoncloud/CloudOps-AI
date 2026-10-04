from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PersistentAuditClaim:
    run_id: str
    event_type: str
    emitted: bool
    evidence: dict[str, Any]
    claim_token: str = ""


class PersistentAuditIdempotencyStore:
    """SQLite-backed audit claim store with retryable pending claims."""

    def __init__(
        self,
        path: str | Path = "cloudops_audit_idempotency.db",
        *,
        lease_seconds: int = 30,
    ) -> None:
        self.path = str(path)
        self.lease_seconds = max(1, int(lease_seconds))
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
                    status TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT NOT NULL DEFAULT '',
                    claimed_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (run_id, event_type)
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(audit_idempotency)"
                ).fetchall()
            }
            if "status" not in columns:
                connection.execute(
                    "ALTER TABLE audit_idempotency "
                    "ADD COLUMN status TEXT NOT NULL DEFAULT 'emitted'"
                )
            if "claim_token" not in columns:
                connection.execute(
                    "ALTER TABLE audit_idempotency "
                    "ADD COLUMN claim_token TEXT NOT NULL DEFAULT ''"
                )
            if "claimed_at" not in columns:
                connection.execute(
                    "ALTER TABLE audit_idempotency "
                    "ADD COLUMN claimed_at REAL NOT NULL DEFAULT 0"
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
        if not isinstance(evidence, dict):
            raise ValueError("evidence must be a dictionary")

        normalized = self._normalize_evidence(evidence)
        token = uuid.uuid4().hex
        now = __import__("time").time()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT evidence_json, status, claim_token, claimed_at
                FROM audit_idempotency
                WHERE run_id = ? AND event_type = ?
                """,
                (run_id, event_type),
            ).fetchone()

            if row is None:
                connection.execute(
                    """
                    INSERT INTO audit_idempotency(
                        run_id, event_type, evidence_json,
                        status, claim_token, claimed_at
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (run_id, event_type, normalized, token, now),
                )
                return PersistentAuditClaim(
                    run_id, event_type, True, dict(evidence), token
                )

            previous = json.loads(row[0])
            if previous != json.loads(normalized):
                raise ValueError("Conflicting audit evidence")

            status = row[1]
            if status == "emitted":
                return PersistentAuditClaim(
                    run_id, event_type, False, dict(evidence), ""
                )

            claimed_at = float(row[3] or 0)
            if now - claimed_at < self.lease_seconds:
                return PersistentAuditClaim(
                    run_id, event_type, False, dict(evidence), ""
                )

            connection.execute(
                """
                UPDATE audit_idempotency
                SET claim_token = ?, claimed_at = ?, status = 'pending'
                WHERE run_id = ? AND event_type = ?
                """,
                (token, now, run_id, event_type),
            )
            return PersistentAuditClaim(
                run_id, event_type, True, dict(evidence), token
            )

    def mark_emitted(
        self,
        run_id: str,
        event_type: str,
        claim_token: str,
    ) -> bool:
        run_id = (run_id or "").strip()
        event_type = (event_type or "").strip()
        claim_token = (claim_token or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        if not event_type:
            raise ValueError("event_type is required")
        if not claim_token:
            raise ValueError("claim_token is required")

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE audit_idempotency
                SET status = 'emitted'
                WHERE run_id = ?
                  AND event_type = ?
                  AND status = 'pending'
                  AND claim_token = ?
                """,
                (run_id, event_type, claim_token),
            )
            return cursor.rowcount == 1

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
        return None
