from concurrent.futures import ThreadPoolExecutor
import sqlite3

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_finalization_has_exactly_one_winner(tmp_path):
    database = tmp_path / "audit.db"
    store = PersistentAuditIdempotencyStore(database)

    claim = store.claim(
        "finalize-race",
        "deployment.completed",
        {"service": "api", "result": "success"},
    )

    assert claim.emitted is True
    assert claim.claim_token

    def finalize():
        worker_store = PersistentAuditIdempotencyStore(database)
        return worker_store.mark_emitted(
            "finalize-race",
            "deployment.completed",
            claim.claim_token,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: finalize(), range(2)))

    assert sorted(results) == [False, True]

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT evidence_json, status, claim_token "
            "FROM audit_idempotency "
            "WHERE run_id = ? AND event_type = ?",
            ("finalize-race", "deployment.completed"),
        ).fetchone()

    assert row is not None
    assert row[0] == '{"result":"success","service":"api"}'
    assert row[1] == "emitted"
    assert row[2] == claim.claim_token
