from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def _create_legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE audit_idempotency (
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                PRIMARY KEY (run_id, event_type)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_idempotency(run_id, event_type, evidence_json)
            VALUES (?, ?, ?)
            """,
            (
                "legacy-run",
                "recovery_completed",
                json.dumps({"action_id": "old-action"}, sort_keys=True),
            ),
        )


def test_legacy_schema_migrates_existing_rows_as_emitted(tmp_path: Path):
    database = tmp_path / "legacy.db"
    _create_legacy_database(database)

    store = PersistentAuditIdempotencyStore(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(audit_idempotency)"
            ).fetchall()
        }
        row = connection.execute(
            """
            SELECT status, claim_token, claimed_at
            FROM audit_idempotency
            WHERE run_id = ? AND event_type = ?
            """,
            ("legacy-run", "recovery_completed"),
        ).fetchone()

    assert {"status", "claim_token", "claimed_at"} <= columns
    assert row == ("emitted", "", 0.0)

    duplicate = store.claim(
        "legacy-run",
        "recovery_completed",
        {"action_id": "old-action"},
    )

    assert duplicate.emitted is False
    assert duplicate.claim_token == ""


def test_migrated_database_accepts_new_claims(tmp_path: Path):
    database = tmp_path / "legacy.db"
    _create_legacy_database(database)

    store = PersistentAuditIdempotencyStore(database)

    new_claim = store.claim(
        "new-run",
        "recovery_failed",
        {"action_id": "new-action"},
    )

    assert new_claim.emitted is True
    assert bool(new_claim.claim_token)
    assert store.contains("new-run", "recovery_failed") is True

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_idempotency"
        ).fetchone()[0]

    assert count == 2
