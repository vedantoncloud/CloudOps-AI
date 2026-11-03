"""MySQL migration smoke tests run only when CI provides a service database."""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


@pytest.mark.skipif(not os.environ.get("CLOUDOPS_MYSQL_TEST_URL"), reason="MySQL CI service is not configured")
def test_shared_persistence_schema_upgrades_and_downgrades_on_mysql():
    url = os.environ["CLOUDOPS_MYSQL_TEST_URL"]
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", url.replace("%", "%%"))
    os.environ["CLOUDOPS_DATABASE_URL"] = url

    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert {
            "audit_events",
            "audit_chain_state",
            "audit_idempotency",
            "action_plans",
            "action_plan_state",
            "gitops_change_sets",
            "gitops_state",
            "alembic_version",
        }.issubset(set(inspector.get_table_names()))
        with engine.connect() as connection:
            state = connection.execute(
                text(
                    "SELECT singleton_id, last_sequence, last_hash "
                    "FROM audit_chain_state"
                )
            ).one()
            assert tuple(state) == (1, 0, "")
            plan_state = connection.execute(
                text(
                    "SELECT singleton_id, last_created_order "
                    "FROM action_plan_state"
                )
            ).one()
            assert tuple(plan_state) == (1, 0)
            gitops_state = connection.execute(
                text(
                    "SELECT singleton_id, last_created_order FROM gitops_state"
                )
            ).one()
            assert tuple(gitops_state) == (1, 0)
        assert {column["name"] for column in inspector.get_columns("audit_idempotency")} >= {
            "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
        }
        idempotency_columns = {
            column["name"]: column for column in inspector.get_columns("audit_idempotency")
        }
        audit_event_json = next(
            column for column in inspector.get_columns("audit_events")
            if column["name"] == "event_json"
        )
        assert "LONGTEXT" in str(audit_event_json["type"]).upper()
        assert "LONGTEXT" in str(idempotency_columns["evidence_json"]["type"]).upper()
        assert "DOUBLE" in str(idempotency_columns["claimed_at"]["type"]).upper()
        for table_name in ("action_plans", "gitops_change_sets"):
            payload = next(
                column for column in inspector.get_columns(table_name)
                if column["name"] == "payload"
            )
            assert "LONGTEXT" in str(payload["type"]).upper()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_idempotency "
                    "(run_id, event_type, evidence_json) "
                    "VALUES (:run, :event, :evidence)"
                ),
                [
                    {"run": "Run-A", "event": "created", "evidence": "{}"},
                    {"run": "run-a", "event": "created", "evidence": "{}"},
                ],
            )
            assert connection.execute(
                text("SELECT COUNT(*) FROM audit_idempotency")
            ).scalar_one() == 2
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert not {
            "audit_events", "audit_chain_state", "audit_idempotency", "action_plans", "action_plan_state", "gitops_change_sets", "gitops_state"
        }.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()
