"""Durable SHA-256 audit chain with legacy SQLite and opt-in shared SQL storage."""

from __future__ import annotations

import hmac
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from autonomy.audit import AuditEvent, AuditIntegrityResult, AuditTrail
from observability import observed_sqlite_connection


class PersistentAuditTrail(AuditTrail):
    """Append-only audit storage with transactional cross-worker chain ordering.

    SQLite remains the default. An explicit database URL selects the Alembic-
    managed shared schema; MySQL appends serialize on the singleton chain-head
    row, while SQLite uses BEGIN IMMEDIATE.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = RLock()
        self._engine: Engine | None = None
        if "://" in self.database_path:
            if not self.database_path.startswith(("mysql+pymysql://", "sqlite:///")):
                raise ValueError("database URL must use mysql+pymysql or sqlite")
            self._engine = create_engine(
                self.database_path,
                pool_pre_ping=True,
                future=True,
            )
            self._validate_shared_schema()
        else:
            with observed_sqlite_connection(self._connect, "audit_events") as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_json TEXT NOT NULL,
                        event_hash TEXT NOT NULL,
                        tenant_id TEXT
                    )"""
                )
                columns = {
                    row["name"] for row in connection.execute(
                        "PRAGMA table_info(audit_events)"
                    ).fetchall()
                }
                if "tenant_id" not in columns:
                    connection.execute("ALTER TABLE audit_events ADD COLUMN tenant_id TEXT")
                legacy_rows = connection.execute(
                    "SELECT sequence, event_json FROM audit_events WHERE tenant_id IS NULL"
                ).fetchall()
                for row in legacy_rows:
                    try:
                        details = json.loads(row["event_json"]).get("details", {})
                        tenant_id = details.get("tenant_id") if isinstance(details, dict) else None
                        if isinstance(tenant_id, str):
                            connection.execute(
                                "UPDATE audit_events SET tenant_id = ? WHERE sequence = ?",
                                (tenant_id, row["sequence"]),
                            )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS ix_audit_events_tenant_sequence "
                    "ON audit_events (tenant_id, sequence)"
                )

    def _validate_shared_schema(self) -> None:
        assert self._engine is not None
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT sequence, event_json, event_hash, tenant_id "
                        "FROM audit_events LIMIT 0"
                    )
                )
                state = connection.execute(
                    text(
                        "SELECT singleton_id, last_sequence, last_hash "
                        "FROM audit_chain_state WHERE singleton_id = 1"
                    )
                ).first()
                if state is None:
                    raise ValueError("shared audit chain head row is missing")
        except (SQLAlchemyError, ValueError) as exc:
            self._engine.dispose()
            self._engine = None
            raise ValueError(
                "Shared audit chain schema is not initialized; run Alembic migrations first"
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def uses_shared_database(self) -> bool:
        return self._engine is not None

    def record_with_connection(self, connection, **kwargs: Any) -> AuditEvent:
        """Append to the audit chain inside a caller-owned SQL transaction."""
        if self._engine is None:
            raise RuntimeError("audit trail is not configured for shared SQL storage")
        if connection.engine.url != self._engine.url:
            raise ValueError("audit trail and lifecycle store must share one database URL")
        event = AuditTrail().record(**kwargs)
        lock_clause = " FOR UPDATE" if connection.dialect.name == "mysql" else ""
        self._append_with_locked_head(connection, event, lock_clause)
        return event

    def record(self, **kwargs: Any) -> AuditEvent:
        validator = AuditTrail()
        event = validator.record(**kwargs)
        if self._engine is not None:
            self._record_shared(event)
            return event

        with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = row["event_hash"] if row else ""
            event_hash = self._calculate_hash(previous_hash, event)
            connection.execute(
                "INSERT INTO audit_events (event_json, event_hash, tenant_id) "
                "VALUES (?, ?, ?)",
                (
                    self._canonical_event(event).decode("utf-8"),
                    event_hash,
                    self._event_tenant_id(event),
                ),
            )
        return event

    def _record_shared(self, event: AuditEvent) -> None:
        assert self._engine is not None
        dialect = self._engine.dialect.name
        if dialect == "mysql":
            with self._engine.begin() as connection:
                self._append_with_locked_head(connection, event, " FOR UPDATE")
            return
        if dialect == "sqlite":
            with self._engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    self._append_with_locked_head(connection, event, "")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return
        raise ValueError(f"Unsupported shared audit dialect: {dialect}")

    def _append_with_locked_head(self, connection, event: AuditEvent, lock_clause: str) -> None:
        state = connection.execute(
            text(
                "SELECT last_sequence, last_hash FROM audit_chain_state "
                "WHERE singleton_id = 1" + lock_clause
            )
        ).mappings().one()
        tail = connection.execute(
            text(
                "SELECT sequence, event_hash FROM audit_events "
                "ORDER BY sequence DESC LIMIT 1"
            )
        ).mappings().first()
        expected_sequence = int(tail["sequence"]) if tail is not None else 0
        expected_hash = str(tail["event_hash"]) if tail is not None else ""
        if (
            int(state["last_sequence"]) != expected_sequence
            or state["last_hash"] != expected_hash
        ):
            raise RuntimeError("Audit chain head metadata is inconsistent")

        sequence = expected_sequence + 1
        event_json = self._canonical_event(event).decode("utf-8")
        event_hash = self._calculate_hash(expected_hash, event)
        connection.execute(
            text(
                "INSERT INTO audit_events (sequence, event_json, event_hash, tenant_id) "
                "VALUES (:sequence, :event_json, :event_hash, :tenant_id)"
            ),
            {
                "sequence": sequence,
                "event_json": event_json,
                "event_hash": event_hash,
                "tenant_id": self._event_tenant_id(event),
            },
        )
        connection.execute(
            text(
                "UPDATE audit_chain_state SET last_sequence = :sequence, "
                "last_hash = :event_hash WHERE singleton_id = 1"
            ),
            {"sequence": sequence, "event_hash": event_hash},
        )

    def _shared_rows(self, statement: str):
        assert self._engine is not None
        with self._engine.connect() as connection:
            return connection.execute(text(statement)).mappings().all()

    @staticmethod
    def _event_tenant_id(event: AuditEvent) -> str | None:
        value = event.details.get("tenant_id")
        return value if isinstance(value, str) else None

    def get_events(
        self,
        action_id: str | None = None,
        *,
        tenant_id: str | None = None,
        tenant_scoped: bool = False,
    ) -> list[AuditEvent]:
        clauses = []
        parameters = {}
        if tenant_scoped:
            if tenant_id is None:
                return []
            clauses.append("tenant_id = :tenant_id")
            parameters["tenant_id"] = tenant_id
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        statement = (
            "SELECT event_json, tenant_id FROM audit_events" + where + " ORDER BY sequence"
        )
        if self._engine is not None:
            assert self._engine is not None
            with self._engine.connect() as connection:
                rows = connection.execute(text(statement), parameters).mappings().all()
        else:
            sqlite_statement = statement.replace(":action_id", "?").replace(":tenant_id", "?")
            sqlite_parameters = tuple(parameters.values())
            with observed_sqlite_connection(self._connect, "audit_events") as connection:
                rows = connection.execute(sqlite_statement, sqlite_parameters).fetchall()
        events = []
        for row in rows:
            event = self._event_from_json(row["event_json"])
            if self._event_tenant_id(event) != row["tenant_id"]:
                continue
            events.append(event)
        if action_id is not None:
            events = [event for event in events if event.action_id == action_id]
        return events

    @staticmethod
    def _event_from_json(payload: str) -> AuditEvent:
        data = json.loads(payload)
        return AuditEvent(**data)

    def get_integrity_diagnostics(self) -> AuditIntegrityResult:
        if self._engine is not None:
            rows = self._shared_rows(
                "SELECT event_json, event_hash FROM audit_events ORDER BY sequence"
            )
        else:
            with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
                rows = connection.execute(
                    "SELECT event_json, event_hash FROM audit_events ORDER BY sequence"
                ).fetchall()
        previous_hash = ""
        for index, row in enumerate(rows):
            try:
                event = self._event_from_json(row["event_json"])
                expected = self._calculate_hash(previous_hash, event)
                stored = row["event_hash"]
                if (
                    not isinstance(stored, str)
                    or len(stored) != 64
                    or not hmac.compare_digest(expected, stored)
                ):
                    return AuditIntegrityResult(False, len(rows), index)
            except Exception:
                return AuditIntegrityResult(False, len(rows), index)
            previous_hash = stored
        return AuditIntegrityResult(True, len(rows), None)

    def get_verifiable_export(self) -> dict[str, Any]:
        if self._engine is not None:
            rows = self._shared_rows(
                "SELECT sequence, event_json, event_hash "
                "FROM audit_events ORDER BY sequence"
            )
        else:
            with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
                rows = connection.execute(
                    "SELECT sequence, event_json, event_hash "
                    "FROM audit_events ORDER BY sequence"
                ).fetchall()
        events = []
        previous_hash = ""
        for index, row in enumerate(rows):
            try:
                event = self._event_from_json(row["event_json"])
                event_json = self._canonical_event(event).decode("utf-8")
                expected = self._calculate_hash(previous_hash, event)
                stored_hash = row["event_hash"]
                if (
                    not isinstance(stored_hash, str)
                    or len(stored_hash) != 64
                    or not hmac.compare_digest(expected, stored_hash)
                ):
                    raise ValueError
            except Exception as exc:
                raise ValueError(f"Audit chain is invalid at index {index}") from exc
            events.append({
                "sequence": row["sequence"],
                "event": json.loads(event_json),
                "previous_hash": previous_hash,
                "event_hash": stored_hash,
            })
            previous_hash = stored_hash
        return {
            "format": "cloudops-audit-chain-v1",
            "algorithm": "sha256",
            "genesis_hash": "",
            "events": events,
            "final_hash": previous_hash,
        }

    def verify_integrity(self) -> bool:
        return self.get_integrity_diagnostics().valid

    def get_integrity_snapshot(self) -> tuple[bool, int]:
        result = self.get_integrity_diagnostics()
        return result.valid, result.event_count

    def clear(self) -> None:
        if self._engine is not None:
            dialect = self._engine.dialect.name
            if dialect == "mysql":
                with self._engine.begin() as connection:
                    connection.execute(
                        text(
                            "SELECT singleton_id FROM audit_chain_state "
                            "WHERE singleton_id = 1 FOR UPDATE"
                        )
                    ).one()
                    connection.execute(text("DELETE FROM audit_events"))
                    connection.execute(
                        text(
                            "UPDATE audit_chain_state SET last_sequence = 0, "
                            "last_hash = '' WHERE singleton_id = 1"
                        )
                    )
                return
            if dialect == "sqlite":
                with self._engine.connect() as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    try:
                        connection.execute(text("DELETE FROM audit_events"))
                        connection.execute(
                            text(
                                "UPDATE audit_chain_state SET last_sequence = 0, "
                                "last_hash = '' WHERE singleton_id = 1"
                            )
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise
                return
            raise ValueError(f"Unsupported shared audit dialect: {dialect}")

        with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
            connection.execute("DELETE FROM audit_events")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_events'")

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
