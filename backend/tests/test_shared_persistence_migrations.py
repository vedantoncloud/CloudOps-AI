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
    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "audit_events",
            "audit_idempotency",
            "action_plans",
            "gitops_change_sets",
        }
        assert {column["name"] for column in inspector.get_columns("audit_idempotency")} == {
            "run_id", "event_type", "evidence_json", "status", "claim_token", "claimed_at"
        }
        assert {column["name"] for column in inspector.get_columns("action_plans")} == {
            "action_id", "tenant_id", "payload", "created_order"
        }
        assert {column["name"] for column in inspector.get_columns("gitops_change_sets")} == {
            "change_id", "tenant_id", "payload", "created_order"
        }
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO audit_events (event_json, event_hash) VALUES (:event, :hash)"),
                {"event": "{}", "hash": "0" * 64},
            )
            assert connection.execute(text("SELECT sequence FROM audit_events")).scalar_one() == 1
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(url)
    try:
        assert not {
            "audit_events", "audit_idempotency", "action_plans", "gitops_change_sets"
        }.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()
