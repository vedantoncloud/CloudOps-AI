"""Read-only, independent reconciliation of legacy SQLite imports.

Run from backend/ with four frozen source snapshots and CLOUDOPS_DATABASE_URL set.
This command only reads source SQLite files and the shared SQL target.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


SOURCE_TABLES = {
    "audit_events": ("audit_events", "sequence"),
    "audit_idempotency": ("audit_idempotency", "run_id, event_type"),
    "action_plans": ("action_plans", "created_order"),
    "gitops": ("gitops_change_sets", "created_order"),
}

TARGET_TABLES = (
    "audit_events",
    "audit_idempotency",
    "action_plans",
    "gitops_change_sets",
    "persistence_import_runs",
    "audit_chain_state",
    "action_plan_state",
    "gitops_state",
)


def _read_source(path: Path, table: str, order_by: str) -> list[dict[str, Any]]:
    resolved = path.resolve(strict=True)
    with sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro", uri=True, timeout=10
    ) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"{table}: source SQLite integrity check failed")
        names = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        required = {
            "audit_events": {"sequence", "event_json", "event_hash"},
            "audit_idempotency": {
                "run_id", "event_type", "evidence_json", "status",
                "claim_token", "claimed_at",
            },
            "action_plans": {"action_id", "tenant_id", "payload", "created_order"},
            "gitops_change_sets": {"change_id", "payload", "created_order"},
        }[table]
        if not required.issubset(names):
            raise ValueError(f"{table}: source schema is incomplete")
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} ORDER BY {order_by}"
            ).fetchall()
        ]


def _source_manifest(rows: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    canonical = {
        name: [{key: row[key] for key in sorted(row)} for row in records]
        for name, records in rows.items()
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest = hashlib.sha256(encoded).hexdigest()
    summary = {
        "manifest_sha256": manifest,
        "counts": {
            "audit_events": len(rows["audit_events"]),
            "audit_idempotency": len(rows["audit_idempotency"]),
            "action_plans": len(rows["action_plans"]),
            "gitops_change_sets": len(rows["gitops"]),
        },
        "audit_final_hash": (
            rows["audit_events"][-1]["event_hash"] if rows["audit_events"] else ""
        ),
        "action_plan_max_order": max(
            (int(row["created_order"]) for row in rows["action_plans"]), default=0
        ),
        "gitops_max_order": max(
            (int(row["created_order"]) for row in rows["gitops"]), default=0
        ),
    }
    return manifest, summary


def _target_rows(connection, table: str, order_by: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            text(f"SELECT * FROM {table} ORDER BY {order_by}")
        ).mappings().all()
    ]



def _audit_chain_valid(rows: list[dict[str, Any]]) -> bool:
    """Independently verify contiguous sequences and persisted event hashes."""
    previous_hash = ""
    for expected_sequence, row in enumerate(rows, start=1):
        if row.get("sequence") != expected_sequence:
            return False
        stored_hash = row.get("event_hash")
        if (
            not isinstance(stored_hash, str)
            or len(stored_hash) != 64
            or any(character not in "0123456789abcdef" for character in stored_hash)
        ):
            return False
        try:
            event = json.loads(row["event_json"])
            if not isinstance(event, dict):
                return False
            canonical_event = json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            expected_hash = hashlib.sha256(
                previous_hash.encode("ascii") + b"\0" + canonical_event
            ).hexdigest()
        except (KeyError, TypeError, ValueError, UnicodeError):
            return False
        if not hmac.compare_digest(expected_hash, stored_hash):
            return False
        previous_hash = stored_hash
    return True


def reconcile(paths: dict[str, Path], database_url: str) -> dict[str, Any]:
    if not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
        raise ValueError("target must use mysql+pymysql or sqlite")
    if set(paths) != set(SOURCE_TABLES):
        raise ValueError("exactly four source SQLite snapshots are required")

    source = {
        name: _read_source(paths[name], table, order_by)
        for name, (table, order_by) in SOURCE_TABLES.items()
    }
    if not _audit_chain_valid(source["audit_events"]):
        raise ValueError("audit source hash chain is invalid")
    manifest, summary = _source_manifest(source)
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    mismatches: list[str] = []
    target_audit_chain_valid = True
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "mysql":
                found = set(connection.execute(text("SHOW TABLES")).scalars())
            else:
                found = set(connection.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )).scalars())
            if not set(TARGET_TABLES).issubset(found):
                raise ValueError("target schema is incomplete; apply Alembic migrations first")

            for name, (target_table, order_by) in SOURCE_TABLES.items():
                actual = _target_rows(connection, target_table, order_by)
                expected = source[name]
                if name == "audit_events" and not _audit_chain_valid(actual):
                    target_audit_chain_valid = False
                    mismatches.append("audit_events_hash_chain")
                if name == "gitops":
                    normalized = []
                    for row in actual:
                        payload = json.loads(row["payload"])
                        normalized.append({
                            "change_id": row["change_id"],
                            "payload": row["payload"],
                            "created_order": row["created_order"],
                        })
                        tenant = (payload.get("metadata") or {}).get("tenant_id")
                        if row.get("tenant_id") != tenant:
                            mismatches.append("gitops_tenant_attribution")
                    actual = normalized
                if actual != expected:
                    mismatches.append(f"{name}_records")
            
            audit_state = connection.execute(text(
                "SELECT last_sequence, last_hash FROM audit_chain_state WHERE singleton_id = 1"
            )).mappings().one_or_none()
            plan_state = connection.execute(text(
                "SELECT last_created_order FROM action_plan_state WHERE singleton_id = 1"
            )).mappings().one_or_none()
            gitops_state = connection.execute(text(
                "SELECT last_created_order FROM gitops_state WHERE singleton_id = 1"
            )).mappings().one_or_none()
            if audit_state is None or (
                int(audit_state["last_sequence"]), audit_state["last_hash"]
            ) != (summary["counts"]["audit_events"], summary["audit_final_hash"]):
                mismatches.append("audit_chain_head")
            if plan_state is None or int(plan_state["last_created_order"]) != summary["action_plan_max_order"]:
                mismatches.append("action_plan_order_head")
            if gitops_state is None or int(gitops_state["last_created_order"]) != summary["gitops_max_order"]:
                mismatches.append("gitops_order_head")

            ledger = connection.execute(text(
                "SELECT manifest_sha256, report_json FROM persistence_import_runs"
            )).mappings().all()
            if len(ledger) != 1:
                mismatches.append("import_ledger_cardinality")
            elif ledger[0]["manifest_sha256"] != manifest:
                mismatches.append("import_ledger_manifest")
            else:
                try:
                    if json.loads(ledger[0]["report_json"]) != summary:
                        mismatches.append("import_ledger_report")
                except (TypeError, ValueError):
                    mismatches.append("import_ledger_report")

            pending = sum(row["status"] == "pending" for row in source["audit_idempotency"])
            emitted = sum(row["status"] == "emitted" for row in source["audit_idempotency"])
            return {
                "status": "ok" if not mismatches else "mismatch",
                "read_only": True,
                "manifest_sha256": manifest,
                "counts": summary["counts"],
                "audit_final_hash": summary["audit_final_hash"],
                "target_audit_chain_valid": target_audit_chain_valid,
                "pending_claims": pending,
                "emitted_claims": emitted,
                "mismatches": sorted(set(mismatches)),
            }
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-events", required=True, type=Path)
    parser.add_argument("--audit-idempotency", required=True, type=Path)
    parser.add_argument("--action-plans", required=True, type=Path)
    parser.add_argument("--gitops", required=True, type=Path)
    args = parser.parse_args(argv)
    database_url = os.getenv("CLOUDOPS_DATABASE_URL")
    if not database_url:
        print(json.dumps({"status": "not_ready", "reason": "database_url_missing"}))
        return 2
    paths = {
        "audit_events": args.audit_events,
        "audit_idempotency": args.audit_idempotency,
        "action_plans": args.action_plans,
        "gitops": args.gitops,
    }
    try:
        result = reconcile(paths, database_url)
    except SQLAlchemyError:
        print(json.dumps({
            "status": "not_ready",
            "reason": "target_database_operation_failed",
        }, sort_keys=True), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({
            "status": "not_ready",
            "reason": type(exc).__name__,
        }, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
