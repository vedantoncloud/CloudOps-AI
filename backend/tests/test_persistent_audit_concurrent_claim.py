from concurrent.futures import ThreadPoolExecutor

from autonomy.persistent_audit_idempotency import (
    PersistentAuditIdempotencyStore,
)


def test_concurrent_claims_allow_only_one_owner(tmp_path):
    database = tmp_path / "concurrent-audit.db"
    evidence = {"action_id": "concurrent-1", "outcome": "failed"}

    stores = [
        PersistentAuditIdempotencyStore(database)
        for _ in range(8)
    ]

    def acquire_claim(store):
        return store.claim(
            "concurrent-run",
            "recovery_failed",
            evidence,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(acquire_claim, stores))

    owners = [claim for claim in claims if claim.emitted]

    assert len(owners) == 1
    assert owners[0].claim_token

    for claim in claims:
        if not claim.emitted:
            assert claim.claim_token == ""

    assert all(claim.evidence == evidence for claim in claims)
