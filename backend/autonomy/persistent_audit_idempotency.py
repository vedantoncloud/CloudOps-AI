from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from observability import observed_sqlite_connection


@dataclass(frozen=True)
class PersistentAuditClaim:
    run_id: str
    event_type: str
    emitted: bool
    evidence: dict[str, Any]
    claim_token: str = ""


class PersistentAuditIdempotencyStore:
    """Durable audit claims with SQLite compatibility and opt-in shared SQL storage.

    Pass an explicit database_url after applying the Alembic schema to use a
    shared MySQL database. Without it, the legacy SQLite path remains unchanged.
    """

    def __init__(
        self,
        path: str | Path = "cloudops_audit_idempotency.db",
        *,
        lease_seconds: int = 30,
        database_url: str | None = None,
    ) -> None:
        if database_url and path != "cloudops_audit_idempotency.db":
            raise ValueError("pass either path or database_url, not both")
        self.path = str(database_url or path)
        self.backend = "sqlalchemy" if database_url else "sqlite"
        self.lease_seconds = max(1, int(lease_seconds))
        self._engine: Engine | None = None
        if database_url:
            if not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
                raise ValueError("database_url must use mysql+pymysql or sqlite")
            self._engine = create_engine(
                database_url,
                pool_pre_ping=True,
                future=True,
            )
            self._validate_shared_schema()
        else:
            self._initialize()

    def _validate_shared_schema(self) -> None:
        assert self._engine is not None
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT run_id, event_type, evidence_json, status, "
                        "claim_token, claimed_at FROM audit_idempotency LIMIT 0"
                    )
                )
        except SQLAlchemyError as exc:
            self._engine.dispose()
            self._engine = None
            raise ValueError(
                "Shared audit idempotency schema is not initialized; run Alembic migrations first"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with observed_sqlite_connection(self._connect, "audit_idempotency") as connection:
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
        now = time.time()

        if self._engine is None:
            return self._claim_sqlite(run_id, event_type, evidence, normalized, token, now)
        return self._claim_sqlalchemy(run_id, event_type, evidence, normalized, token, now)

    def _claim_sqlalchemy(
        self,
        run_id: str,
        event_type: str,
        evidence: dict[str, Any],
        normalized: str,
        token: str,
        now: float,
    ) -> PersistentAuditClaim:
        assert self._engine is not None
        dialect = self._engine.dialect.name
        if dialect == "mysql":
            insert_sql = """
                INSERT INTO audit_idempotency(
                    run_id, event_type, evidence_json, status, claim_token, claimed_at
                ) VALUES (:run_id, :event_type, :evidence_json, 'pending', :token, :now)
                ON DUPLICATE KEY UPDATE run_id = VALUES(run_id)
            """
            lock_clause = " FOR UPDATE"
        elif dialect == "sqlite":
            insert_sql = """
                INSERT OR IGNORE INTO audit_idempotency(
                    run_id, event_type, evidence_json, status, claim_token, claimed_at
                ) VALUES (:run_id, :event_type, :evidence_json, 'pending', :token, :now)
            """
            lock_clause = ""
        else:
            raise ValueError(f"Unsupported shared persistence dialect: {dialect}")

        params = {
            "run_id": run_id,
            "event_type": event_type,
            "evidence_json": normalized,
            "token": token,
            "now": now,
        }
        with self._engine.begin() as connection:
            # MySQL's duplicate-key write serializes competing creators on the
            # composite primary key before the locking read below.
            connection.execute(text(insert_sql), params)
            row = connection.execute(
                text(
                    "SELECT evidence_json, status, claim_token, claimed_at "
                    "FROM audit_idempotency WHERE run_id = :run_id "
                    "AND event_type = :event_type" + lock_clause
                ),
                {"run_id": run_id, "event_type": event_type},
            ).mappings().one()

            if json.loads(row["evidence_json"]) != json.loads(normalized):
                raise ValueError("Conflicting audit evidence")
            if row["status"] == "emitted":
                return PersistentAuditClaim(run_id, event_type, False, dict(evidence), "")
            if row["claim_token"] == token:
                return PersistentAuditClaim(run_id, event_type, True, dict(evidence), token)

            claimed_at = float(row["claimed_at"] or 0)
            if now - claimed_at < self.lease_seconds:
                return PersistentAuditClaim(run_id, event_type, False, dict(evidence), "")

            connection.execute(
                text(
                    "UPDATE audit_idempotency SET claim_token = :token, "
                    "claimed_at = :now, status = 'pending' "
                    "WHERE run_id = :run_id AND event_type = :event_type"
                ),
                params,
            )
            return PersistentAuditClaim(run_id, event_type, True, dict(evidence), token)

    def _claim_sqlite(
        self,
        run_id: str,
        event_type: str,
        evidence: dict[str, Any],
        normalized: str,
        token: str,
        now: float,
    ) -> PersistentAuditClaim:
        with observed_sqlite_connection(self._connect, "audit_idempotency") as connection:
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
                return PersistentAuditClaim(run_id, event_type, True, dict(evidence), token)

            previous = json.loads(row[0])
            if previous != json.loads(normalized):
                raise ValueError("Conflicting audit evidence")
            if row[1] == "emitted":
                return PersistentAuditClaim(run_id, event_type, False, dict(evidence), "")
            if row[2] == token:
                return PersistentAuditClaim(run_id, event_type, True, dict(evidence), token)

            claimed_at = float(row[3] or 0)
            if now - claimed_at < self.lease_seconds:
                return PersistentAuditClaim(run_id, event_type, False, dict(evidence), "")

            connection.execute(
                """
                UPDATE audit_idempotency
                SET claim_token = ?, claimed_at = ?, status = 'pending'
                WHERE run_id = ? AND event_type = ?
                """,
                (token, now, run_id, event_type),
            )
            return PersistentAuditClaim(run_id, event_type, True, dict(evidence), token)

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

        if self._engine is not None:
            with self._engine.begin() as connection:
                result = connection.execute(
                    text(
                        "UPDATE audit_idempotency SET status = 'emitted' "
                        "WHERE run_id = :run_id AND event_type = :event_type "
                        "AND status = 'pending' AND claim_token = :claim_token"
                    ),
                    {
                        "run_id": run_id,
                        "event_type": event_type,
                        "claim_token": claim_token,
                    },
                )
                return result.rowcount == 1

        with observed_sqlite_connection(self._connect, "audit_idempotency") as connection:
            cursor = connection.execute(
                """
                UPDATE audit_idempotency SET status = 'emitted'
                WHERE run_id = ? AND event_type = ? AND status = 'pending'
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

        if self._engine is not None:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT 1 FROM audit_idempotency "
                        "WHERE run_id = :run_id AND event_type = :event_type"
                    ),
                    {"run_id": run_id, "event_type": event_type},
                ).first()
            return row is not None

        with observed_sqlite_connection(self._connect, "audit_idempotency") as connection:
            row = connection.execute(
                "SELECT 1 FROM audit_idempotency WHERE run_id = ? AND event_type = ?",
                (run_id, event_type),
            ).fetchone()
        return row is not None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
