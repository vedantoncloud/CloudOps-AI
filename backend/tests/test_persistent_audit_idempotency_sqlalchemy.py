"""Dialect-neutral SQLAlchemy store contract tests using a migrated SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.config import Config

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore
from autonomy.persistent_audit_reconciliation import PersistentAuditReconciliation


@pytest.fixture
def shared_database_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shared-audit.db'}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def test_sqlalchemy_store_claims_and_fences_stale_tokens(shared_database_url):
    store = PersistentAuditIdempotencyStore(
        database_url=shared_database_url,
        lease_seconds=1,
    )
    try:
        first = store.claim("run-sqlalchemy", "event", {"id": 1})
        duplicate = store.claim("run-sqlalchemy", "event", {"id": 1})
        assert first.emitted is True
        assert duplicate.emitted is False

        from sqlalchemy import create_engine, text

        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE audit_idempotency SET claimed_at = 1 "
                        "WHERE run_id = 'run-sqlalchemy' AND event_type = 'event'"
                    )
                )
        finally:
            engine.dispose()

        reclaimed = store.claim("run-sqlalchemy", "event", {"id": 1})
        assert reclaimed.emitted is True
        assert reclaimed.claim_token != first.claim_token
        assert store.mark_emitted("run-sqlalchemy", "event", first.claim_token) is False
        assert store.mark_emitted("run-sqlalchemy", "event", reclaimed.claim_token) is True
    finally:
        store.close()


def test_sqlalchemy_health_and_reconciliation_remain_read_only(shared_database_url):
    store = PersistentAuditIdempotencyStore(database_url=shared_database_url)
    try:
        pending = store.claim("run-health", "pending", {"source": "test"})
        emitted = store.claim("run-health", "emitted", {"source": "test"})
        assert store.mark_emitted("run-health", "emitted", emitted.claim_token)

        checker = PersistentAuditHealthChecker(shared_database_url)
        before = checker.inspect()
        listed = checker.list_pending()
        result = PersistentAuditReconciliation(
            store,
            lease_seconds=300,
            now=datetime.now(timezone.utc),
        ).inspect()
        after = checker.inspect()

        assert before.total_claims == 2
        assert before.pending_claims == 1
        assert before.emitted_claims == 1
        assert before.evidence["store"] == "sqlite"
        assert before.evidence["read_only"] is True
        assert [item["run_id"] for item in listed] == ["run-health"]
        assert result.count == 1
        assert result.evidence["store"] == "sqlite"
        assert before.total_claims == after.total_claims
        assert pending.claim_token
    finally:
        store.close()


def test_shared_store_requires_an_applied_schema(shared_database_url, tmp_path):
    missing_url = f"sqlite:///{tmp_path / 'not-migrated.db'}"
    with pytest.raises(ValueError, match="run Alembic migrations first"):
        PersistentAuditIdempotencyStore(database_url=missing_url)
