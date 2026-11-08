from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _config(database_url: str) -> Config:
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_shared_persistence_schema_migrates_and_downgrades_on_sqlite(tmp_path, monkeypatch):
    database = tmp_path / "shared-persistence.db"
    url = f"sqlite:///{database}"
    monkeypatch.setenv("CLOUDOPS_DATABASE_URL", url)

    config = _config(url)
    command.upgrade(config, "0001_shared_persistence")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_events (sequence, event_json, event_hash) "
                "VALUES (1, :event, :hash)"
            ),
            {"event": "{}", "hash": "1" * 64},
        )
    command.upgrade(config, "0002_audit_chain_head_lock")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO action_plans "
                "(action_id, tenant_id, payload, created_order) "
                "VALUES ('legacy-plan', 'tenant-a', '{}', 7)"
            )
        )
    command.upgrade(config, "0003_action_plan_order_lock")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gitops_change_sets "
                "(change_id, tenant_id, payload, created_order) "
                "VALUES ('legacy-change', 'tenant-a', '{}', 11)"
            )
        )
    command.upgrade(config, "head")
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "audit_events",
            "audit_chain_state",
            "audit_idempotency",
            "action_plans",
            "action_plan_state",
            "gitops_change_sets",
            "gitops_state",
            "persistence_import_runs",
            "rate_limit_counters",
        }
        assert {column["name"] for column in inspector.get_columns("audit_idempotency")} == {
            "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
        }
        with engine.connect() as connection:
            state = connection.execute(
                text(
                    "SELECT singleton_id, last_sequence, last_hash "
                    "FROM audit_chain_state"
                )
            ).one()
            assert tuple(state) == (1, 1, "1" * 64)
        assert {column["name"] for column in inspector.get_columns("action_plans")} == {
            "action_id", "tenant_id", "payload", "created_order"
        }
        with engine.connect() as connection:
            plan_state = connection.execute(
                text(
                    "SELECT singleton_id, last_created_order "
                    "FROM action_plan_state"
                )
            ).one()
            assert tuple(plan_state) == (1, 7)
        assert {column["name"] for column in inspector.get_columns("gitops_change_sets")} == {
            "change_id", "tenant_id", "payload", "created_order"
        }
        with engine.connect() as connection:
            gitops_state = connection.execute(
                text(
                    "SELECT singleton_id, last_created_order FROM gitops_state"
                )
            ).one()
            assert tuple(gitops_state) == (1, 11)
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO audit_events (event_json, event_hash) VALUES (:event, :hash)"),
                {"event": "{}", "hash": "0" * 64},
            )
            assert connection.execute(text("SELECT MAX(sequence) FROM audit_events")).scalar_one() == 2
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert not {
            "audit_events", "audit_chain_state", "audit_idempotency", "action_plans", "action_plan_state", "gitops_change_sets", "gitops_state", "persistence_import_runs", "rate_limit_counters"
        }.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()
