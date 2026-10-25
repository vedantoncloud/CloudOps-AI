"""SQLite-backed durable audit events with the same hash-chain contract."""

from __future__ import annotations

import json
import hmac
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from autonomy.audit import AuditEvent, AuditIntegrityResult, AuditTrail
from observability import observed_sqlite_connection


class PersistentAuditTrail(AuditTrail):
    """Append-only audit storage that survives process restarts.

    The database path is always explicit. Callers can select a dedicated file
    and this class never chooses or discovers another database.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = RLock()
        with observed_sqlite_connection(self._connect, "audit_events") as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, **kwargs: Any) -> AuditEvent:
        # Reuse the in-memory implementation for input validation, defensive
        # copies, and canonical JSON validation before opening a write txn.
        validator = AuditTrail()
        event = validator.record(**kwargs)
        with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = row["event_hash"] if row else ""
            event_hash = self._calculate_hash(previous_hash, event)
            connection.execute(
                "INSERT INTO audit_events (event_json, event_hash) VALUES (?, ?)",
                (self._canonical_event(event).decode("utf-8"), event_hash),
            )
        return event

    def get_events(self, action_id: str | None = None) -> list[AuditEvent]:
        with observed_sqlite_connection(self._connect, "audit_events") as connection:
            rows = connection.execute(
                "SELECT event_json FROM audit_events ORDER BY sequence"
            ).fetchall()
        events = [self._event_from_json(row["event_json"]) for row in rows]
        return events if action_id is None else [
            event for event in events if event.action_id == action_id
        ]

    @staticmethod
    def _event_from_json(payload: str) -> AuditEvent:
        data = json.loads(payload)
        return AuditEvent(**data)

    def get_integrity_diagnostics(self) -> AuditIntegrityResult:
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
        """Return a full ordered chain snapshot suitable for offline verification."""
        with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
            rows = connection.execute(
                "SELECT sequence, event_json, event_hash FROM audit_events ORDER BY sequence"
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
        with self._lock, observed_sqlite_connection(self._connect, "audit_events") as connection:
            connection.execute("DELETE FROM audit_events")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_events'")
