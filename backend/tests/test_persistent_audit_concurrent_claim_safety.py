from concurrent.futures import ThreadPoolExecutor
import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_claims_allow_only_one_active_owner(tmp_path):
    database = tmp_path / "audit.db"
    evidence = {"service": "api", "result": "success"}

    def acquire():
        store = PersistentAuditIdempotencyStore(database)
        return store.claim(
            "concurrent-run",
            "deployment.completed",
            evidence,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: acquire(), range(2)))

    owners = [claim for claim in claims if claim.emitted]

    assert len(owners) == 1
    assert owners[0].claim_token
    assert sum(bool(claim.claim_token) for claim in claims) == 1

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT run_id, event_type, evidence_json, status, claim_token "
            "FROM audit_idempotency"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0:2] == (
        "concurrent-run",
        "deployment.completed",
    )
    assert rows[0][3] == "pending"
    assert rows[0][4] == owners[0].claim_token
