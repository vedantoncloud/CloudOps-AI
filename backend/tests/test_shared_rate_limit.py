"""Shared SQL request-rate limiter tests using migrated SQLite storage."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from rate_limit import SharedSQLRequestRateLimiter


@pytest.fixture
def shared_database_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared-rate-limits.db'}"
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def test_two_limiter_instances_share_one_atomic_counter(shared_database_url):
    first = SharedSQLRequestRateLimiter(3, 60, shared_database_url, clock=lambda: 5)
    second = SharedSQLRequestRateLimiter(3, 60, shared_database_url, clock=lambda: 5)
    try:
        assert first.allow("tenant-a:operator-1") == (True, 55)
        assert second.allow("tenant-a:operator-1") == (True, 55)
        assert first.allow("tenant-a:operator-1") == (True, 55)
        assert second.allow("tenant-a:operator-1") == (False, 55)
    finally:
        first.close()
        second.close()


def test_shared_counters_are_isolated_and_reset_by_window(shared_database_url):
    now = [0]
    first = SharedSQLRequestRateLimiter(1, 10, shared_database_url, clock=lambda: now[0])
    second = SharedSQLRequestRateLimiter(1, 10, shared_database_url, clock=lambda: now[0])
    try:
        assert first.allow("tenant-a:alice") == (True, 10)
        assert second.allow("tenant-a:alice") == (False, 10)
        assert second.allow("tenant-b:alice") == (True, 10)
        now[0] = 10
        assert second.allow("tenant-a:alice") == (True, 10)
    finally:
        first.close()
        second.close()


def test_concurrent_workers_never_exceed_shared_limit(shared_database_url):
    limit = 5
    limiters = [SharedSQLRequestRateLimiter(limit, 60, shared_database_url, clock=lambda: 5) for _ in range(3)]
    try:
        def request(index):
            return limiters[index % len(limiters)].allow("tenant-a:operator-1")[0]
        with ThreadPoolExecutor(max_workers=9) as executor:
            allowed = list(executor.map(request, range(27)))
        assert sum(allowed) == limit
    finally:
        for limiter in limiters:
            limiter.close()


def test_shared_limiter_requires_migrated_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'not-migrated.db'}"
    with pytest.raises(RuntimeError, match="apply the CloudOps Alembic migrations"):
        SharedSQLRequestRateLimiter(10, 60, url)


def test_shared_limiter_rejects_unsupported_database_url():
    with pytest.raises(ValueError, match="requires mysql+pymysql or sqlite"):
        SharedSQLRequestRateLimiter(10, 60, "postgresql://localhost/cloudops")


def test_shared_limiter_hashes_identity_before_persisting(shared_database_url):
    from sqlalchemy import create_engine, text
    limiter = SharedSQLRequestRateLimiter(10, 60, shared_database_url, clock=lambda: 5)
    try:
        raw_identity = "principal:8:tenant-a:5:alice"
        limiter.allow(raw_identity)
        engine = create_engine(shared_database_url, future=True)
        try:
            with engine.connect() as connection:
                stored = connection.execute(text("SELECT bucket_key FROM rate_limit_counters")).scalar_one()
            assert stored != raw_identity
            assert len(stored) == 64
        finally:
            engine.dispose()
    finally:
        limiter.close()
