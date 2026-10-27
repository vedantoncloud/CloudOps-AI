"""Validate a CloudOps SQLite backup by loading it in an isolated temporary copy."""

from __future__ import annotations

import argparse
import gc
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from autonomy.action_plan_store import ActionPlanStore
from autonomy.gitops_registry import GitOpsChangeSetRegistry
from autonomy.persistent_audit_trail import PersistentAuditTrail


TABLES = {
    "audit": "audit_events",
    "action-plans": "action_plans",
    "gitops": "gitops_change_sets",
}


def _load_copy(store: str, path: Path) -> int:
    if store == "audit":
        restored = PersistentAuditTrail(path)
        integrity = restored.get_integrity_diagnostics()
        if not integrity.valid:
            raise ValueError(f"Audit hash chain failed at event {integrity.first_invalid_index}")
        return integrity.event_count
    if store == "action-plans":
        return len(ActionPlanStore(path).load_all())
    return len(GitOpsChangeSetRegistry(database_path=path).list_all())


def verify_backup(store: str, backup: Path) -> dict[str, int | str]:
    """Check SQLite integrity and application-level readability without changing backup."""
    source = backup.resolve(strict=True)
    with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=5) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if result != ("ok",):
            raise ValueError("SQLite integrity check failed")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if TABLES[store] not in tables:
            raise ValueError(f"Backup does not contain the expected {store} store")

    with tempfile.TemporaryDirectory(prefix="cloudops-restore-drill-") as temporary:
        isolated_copy = Path(temporary) / "restore.db"
        shutil.copyfile(source, isolated_copy)
        count = _load_copy(store, isolated_copy)
        gc.collect()
    return {"store": store, "records_loaded": count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", choices=sorted(TABLES))
    parser.add_argument("backup", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_backup(args.store, args.backup)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"Backup restore drill failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
