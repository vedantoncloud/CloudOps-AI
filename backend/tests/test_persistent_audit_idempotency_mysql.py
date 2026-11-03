"""Cross-connection idempotency contract tests against the MySQL CI service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="MySQL CI service is not configured")


@pytest.fixture(scope="module")
def database_url():
    assert MYSQL_URL
    os.environ["CLOUDOPS_DATABASE_URL"] = MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield MYSQL_URL


def _identity():
    return f"mysql-contract-{uuid.uuid4().hex}"


def test_first_claim_and_duplicate_are_serialized_across_connections(database_url):
    identity = _identity()
    evidence = {"action_id": identity, "result": "failed"}

    def claim_once():
        store = PersistentAuditIdempotencyStore(database_url=database_url)
        try:
            return store.claim(identity, "recovery_failed", evidence)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: claim_once(), range(8)))

    winners = [claim for claim in claims if claim.emitted]
    assert len(winners) == 1
    assert winners[0].claim_token
    assert sum(not claim.emitted for claim in claims) == 7


def test_stale_claim_recovery_fences_the_previous_token(database_url):
    identity = _identity()
    store = PersistentAuditIdempotencyStore(database_url=database_url, lease_seconds=1)
    try:
        first = store.claim(identity, "recovery_failed", {"id": identity})
        assert first.emitted

        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE audit_idempotency SET claimed_at = :old "
                        "WHERE run_id = :run_id AND event_type = :event_type"
                    ),
                    {
                        "old": 1.0,
                        "run_id": identity,
                        "event_type": "recovery_failed",
                    },
                )
        finally:
            engine.dispose()

        second = store.claim(identity, "recovery_failed", {"id": identity})
        assert second.emitted
        assert second.claim_token != first.claim_token
        assert store.mark_emitted(identity, "recovery_failed", first.claim_token) is False
        assert store.mark_emitted(identity, "recovery_failed", second.claim_token) is True
        assert store.claim(identity, "recovery_failed", {"id": identity}).emitted is False
    finally:
        store.close()


def test_evidence_conflicts_and_case_sensitive_identifiers_are_preserved(database_url):
    identity = _identity()
    store = PersistentAuditIdempotencyStore(database_url=database_url)
    try:
        original = store.claim(identity, "Created", {"owner": "A"})
        with pytest.raises(ValueError, match="Conflicting audit evidence"):
            store.claim(identity, "Created", {"owner": "B"})

        lower = store.claim(identity.lower(), "Created", {"owner": "A"})
        assert original.emitted is True
        assert lower.emitted is True
    finally:
        store.close()


def test_shared_health_and_reconciliation_are_read_only(database_url):
    identity = _identity()
    store = PersistentAuditIdempotencyStore(database_url=database_url)
    try:
        pending = store.claim(identity, "pending_event", {"run_id": identity})
        emitted = store.claim(identity, "emitted_event", {"run_id": identity})
        assert store.mark_emitted(identity, "emitted_event", emitted.claim_token)

        checker = PersistentAuditHealthChecker(database_url)
        before = checker.inspect()
        pending_rows = checker.list_pending()
        result = PersistentAuditReconciliation(
            store,
            lease_seconds=300,
            now=datetime.now(timezone.utc),
        ).inspect()
        after = checker.inspect()

        assert before.total_claims == after.total_claims
        assert before.pending_claims == after.pending_claims
        assert before.evidence["store"] == "mysql"
        assert before.evidence["read_only"] is True
        assert any(row["run_id"] == identity for row in pending_rows)
        assert any(item.run_id == identity for item in result.items)
        assert result.evidence["store"] == "mysql"
        assert pending.claim_token
    finally:
        store.close()
