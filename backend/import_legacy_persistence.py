"""Dry-run-first, atomic importer for the four legacy SQLite persistence stores.

Run from backend/ with CLOUDOPS_DATABASE_URL set:
  python import_legacy_persistence.py --audit-events /secure/audit.db \
      --audit-idempotency /secure/idempotency.db \
      --action-plans /secure/action-plans.db --gitops /secure/gitops.db
Add --apply only after reviewing the dry-run manifest.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_trail import PersistentAuditTrail


TABLES = {
    "audit_events": ("audit_events", "sequence"),
    "audit_idempotency": ("audit_idempotency", ("run_id", "event_type")),
    "action_plans": ("action_plans", "action_id"),
    "gitops": ("gitops_change_sets", "change_id"),
}


def _read_rows(path: Path, table: str, order_by: str) -> list[dict[str, Any]]:
    source = path.resolve(strict=True)
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"{table} source failed SQLite integrity validation")
        names = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        required = {
            "audit_events": {"sequence", "event_json", "event_hash"},
            "audit_idempotency": {
                "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
            },
            "action_plans": {"action_id", "tenant_id", "payload", "created_order"},
            "gitops_change_sets": {"change_id", "payload", "created_order"},
        }[table]
        if not required.issubset(names):
            raise ValueError(f"{table} source schema is incomplete")
        rows = connection.execute(
            f"SELECT * FROM {table} ORDER BY {order_by}"
        ).fetchall()
        return [dict(row) for row in rows]


def _validate_sources(paths: dict[str, Path]) -> dict[str, list[dict[str, Any]]]:
    rows = {
        "audit_events": _read_rows(paths["audit_events"], "audit_events", "sequence"),
        "audit_idempotency": _read_rows(
            paths["audit_idempotency"], "audit_idempotency", "run_id, event_type"
        ),
        "action_plans": _read_rows(paths["action_plans"], "action_plans", "created_order"),
        "gitops": _read_rows(paths["gitops"], "gitops_change_sets", "created_order"),
    }

    audit = PersistentAuditTrail(paths["audit_events"])
    try:
        integrity = audit.get_integrity_diagnostics()
        if not integrity.valid or integrity.event_count != len(rows["audit_events"]):
            raise ValueError("audit source hash chain is invalid")
    finally:
        audit.close()

    health = PersistentAuditHealthChecker(paths["audit_idempotency"]).inspect()
    if (
        not health.evidence.get("consistent")
        or health.evidence.get("malformed_evidence_claims", 0)
        or health.total_claims != len(rows["audit_idempotency"])
    ):
        raise ValueError("audit idempotency source has inconsistent claims")
    for row in rows["audit_idempotency"]:
        if row["status"] not in {"pending", "emitted"}:
            raise ValueError("audit idempotency source has an unknown claim state")
        evidence = json.loads(row["evidence_json"])
        if not isinstance(evidence, dict):
            raise ValueError("audit idempotency evidence must be an object")
        if row["status"] == "pending" and not row["claim_token"]:
            raise ValueError("pending idempotency claim is missing its fencing token")

    audit_sequences = [int(row["sequence"]) for row in rows["audit_events"]]
    if audit_sequences != list(range(1, len(audit_sequences) + 1)):
        raise ValueError("audit event sequence is not contiguous from one")

    for row in rows["audit_idempotency"]:
        if not isinstance(row["run_id"], str) or not isinstance(row["event_type"], str):
            raise ValueError("idempotency key fields must be strings")
        if len(row["run_id"]) > 255 or len(row["event_type"]) > 255:
            raise ValueError("idempotency key exceeds the shared schema length limit")
        if not isinstance(row["claim_token"], str) or len(row["claim_token"]) > 64:
            raise ValueError("idempotency claim token is invalid for the shared schema")
    for row in rows["action_plans"]:
        payload = json.loads(row["payload"])
        if payload.get("action_id") != row["action_id"]:
            raise ValueError("action-plan payload ID does not match its primary key")
        if not isinstance(row["action_id"], str) or (
            row["tenant_id"] is not None and not isinstance(row["tenant_id"], str)
        ):
            raise ValueError("action-plan identifier or tenant must be a string")
        if len(row["action_id"]) > 255 or (
            row["tenant_id"] is not None and len(row["tenant_id"]) > 255
        ):
            raise ValueError("action-plan identifier or tenant exceeds the shared schema length limit")
    for row in rows["gitops"]:
        payload = json.loads(row["payload"])
        if payload.get("change_id") != row["change_id"]:
            raise ValueError("GitOps payload ID does not match its primary key")
        metadata = payload.get("metadata") or {}
        tenant = metadata.get("tenant_id")
        if tenant is not None and not isinstance(tenant, str):
            raise ValueError("GitOps tenant ownership metadata is invalid")
        if len(row["change_id"]) > 255 or (tenant is not None and len(tenant) > 255):
            raise ValueError("GitOps identifier or tenant exceeds the shared schema length limit")
    return rows


def _canonical_manifest(rows: dict[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    serializable = {
        name: [
            {key: row[key] for key in sorted(row)}
            for row in table_rows
        ]
        for name, table_rows in rows.items()
    }
    encoded = json.dumps(
        serializable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    summary = {
        "manifest_sha256": digest,
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
    return digest, summary


def _validate_target(engine: Engine) -> None:
    if engine.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("target database must be MySQL or SQLite")
    with engine.connect() as connection:
        required = {
            "audit_events", "audit_idempotency", "action_plans",
            "gitops_change_sets", "audit_chain_state", "action_plan_state",
            "gitops_state", "persistence_import_runs",
        }
        if engine.dialect.name == "mysql":
            found = set(connection.execute(text("SHOW TABLES")).scalars())
        else:
            found = set(connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).scalars())
        if not required.issubset(found):
            raise ValueError("target schema is incomplete; run Alembic migrations first")
        for table in ("audit_events", "audit_idempotency", "action_plans", "gitops_change_sets"):
            if connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
                raise ValueError("target persistence tables are not empty; refusing import")
        if connection.execute(
            text("SELECT COUNT(*) FROM persistence_import_runs")
        ).scalar_one():
            raise ValueError("target already contains a different import ledger entry")
        for table in ("audit_chain_state", "action_plan_state", "gitops_state"):
            row = connection.execute(
                text(f"SELECT singleton_id FROM {table} WHERE singleton_id = 1")
            ).first()
            if row is None:
                raise ValueError("target singleton state row is missing")


def _dry_run_or_import(
    engine: Engine,
    rows: dict[str, list[dict[str, Any]]],
    manifest_hash: str,
    summary: dict[str, Any],
    apply: bool,
) -> dict[str, Any]:
    with engine.connect() as connection:
        existing = connection.execute(
            text(
                "SELECT report_json FROM persistence_import_runs "
                "WHERE manifest_sha256 = :manifest"
            ),
            {"manifest": manifest_hash},
        ).scalar_one_or_none()
    if existing is not None:
        return {"status": "already_imported", **summary}

    _validate_target(engine)
    if not apply:
        return {"status": "dry_run", "read_only": True, **summary}

    now = datetime.now(timezone.utc).isoformat()
    report_json = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    # One target transaction: either all four stores and all state heads import,
    # or none do. The ledger row is the commit marker and retry fence.
    with engine.begin() as connection:
        if rows["audit_events"]:
            connection.execute(
                text(
                    "INSERT INTO audit_events (sequence, event_json, event_hash) "
                    "VALUES (:sequence, :event_json, :event_hash)"
                ),
                rows["audit_events"],
            )
        if rows["audit_idempotency"]:
            connection.execute(
                text(
                    "INSERT INTO audit_idempotency "
                    "(run_id, event_type, evidence_json, status, claim_token, claimed_at) "
                    "VALUES (:run_id, :event_type, :evidence_json, :status, :claim_token, :claimed_at)"
                ),
                rows["audit_idempotency"],
            )
        if rows["action_plans"]:
            connection.execute(
                text(
                    "INSERT INTO action_plans (action_id, tenant_id, payload, created_order) "
                    "VALUES (:action_id, :tenant_id, :payload, :created_order)"
                ),
                rows["action_plans"],
            )
        gitops_rows = []
        for row in rows["gitops"]:
            payload = json.loads(row["payload"])
            tenant_id = (payload.get("metadata") or {}).get("tenant_id")
            gitops_rows.append({
                "change_id": row["change_id"],
                "tenant_id": tenant_id,
                "payload": row["payload"],
                "created_order": row["created_order"],
            })
        if gitops_rows:
            connection.execute(
                text(
                    "INSERT INTO gitops_change_sets "
                    "(change_id, tenant_id, payload, created_order) "
                    "VALUES (:change_id, :tenant_id, :payload, :created_order)"
                ),
                gitops_rows,
            )
        final_hash = summary["audit_final_hash"]
        connection.execute(
            text(
                "UPDATE audit_chain_state SET last_sequence = :sequence, "
                "last_hash = :last_hash WHERE singleton_id = 1"
            ),
            {"sequence": summary["counts"]["audit_events"], "last_hash": final_hash},
        )
        connection.execute(
            text(
                "UPDATE action_plan_state SET last_created_order = :last_order "
                "WHERE singleton_id = 1"
            ),
            {"last_order": summary["action_plan_max_order"]},
        )
        connection.execute(
            text(
                "UPDATE gitops_state SET last_created_order = :last_order "
                "WHERE singleton_id = 1"
            ),
            {"last_order": summary["gitops_max_order"]},
        )
        connection.execute(
            text(
                "INSERT INTO persistence_import_runs "
                "(manifest_sha256, report_json, imported_at) "
                "VALUES (:manifest, :report, :imported_at)"
            ),
            {
                "manifest": manifest_hash,
                "report": report_json,
                "imported_at": now,
            },
        )
    return {"status": "imported", **summary}


def run_import(
    paths: dict[str, Path],
    database_url: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    if not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
        raise ValueError("target must use mysql+pymysql or sqlite")
    resolved_paths = {name: Path(path) for name, path in paths.items()}
    if set(resolved_paths) != {"audit_events", "audit_idempotency", "action_plans", "gitops"}:
        raise ValueError("exactly four source SQLite files are required")
    canonical_paths = [path.resolve(strict=True) for path in resolved_paths.values()]
    if len(set(canonical_paths)) != 4:
        raise ValueError("each persistence store must come from a distinct SQLite source file")
    rows = _validate_sources(resolved_paths)
    manifest_hash, summary = _canonical_manifest(rows)
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        return _dry_run_or_import(engine, rows, manifest_hash, summary, apply)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-events", required=True, type=Path)
    parser.add_argument("--audit-idempotency", required=True, type=Path)
    parser.add_argument("--action-plans", required=True, type=Path)
    parser.add_argument("--gitops", required=True, type=Path)
    parser.add_argument(
        "--apply", action="store_true",
        help="perform the atomic import; default is a read-only dry run",
    )
    args = parser.parse_args(argv)
    import os
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
        result = run_import(paths, database_url, apply=args.apply)
    except SQLAlchemyError:
        print(json.dumps({
            "status": "not_ready",
            "reason": "target_database_operation_failed",
        }, sort_keys=True), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({
            "status": "not_ready",
            "reason": str(exc),
        }, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
