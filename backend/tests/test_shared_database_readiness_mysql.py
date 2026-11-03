"""Exercise the real shared-database readiness probe against MySQL 8.4."""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config

import main


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(
    not MYSQL_URL,
    reason="MySQL CI service is not configured",
)


def test_mysql_readiness_accepts_the_complete_migrated_shared_schema():
    assert MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")

    assert main._shared_database_ready(MYSQL_URL)
