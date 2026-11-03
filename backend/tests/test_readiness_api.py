from fastapi.testclient import TestClient
from fastapi import FastAPI

import main
from auth import AccessControlMiddleware, Principal


def test_health_is_liveness_and_does_not_probe_aws(monkeypatch):
    def fail_if_called():
        raise AssertionError("liveness must not depend on AWS")

    monkeypatch.setattr(main.aws_service, "get_status", fail_if_called)

    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "cloudops-ai"}


def test_readiness_reports_aws_dependency_without_exposing_account_details(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_status",
        lambda: {"status": "connected", "account_id": "sensitive", "arn": "sensitive"},
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "cloudops-ai",
        "dependencies": {
            "aws": "healthy",
            "audit_events": "healthy",
            "audit_idempotency": "healthy",
            "action_plans": "healthy",
            "gitops_changes": "healthy",
        },
    }


def test_readiness_returns_service_unavailable_when_aws_is_down(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_status",
        lambda: {"status": "disconnected", "error": "credential details"},
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "not_ready",
            "service": "cloudops-ai",
            "dependencies": {
                "aws": "unhealthy",
                "audit_events": "healthy",
                "audit_idempotency": "healthy",
                "action_plans": "healthy",
                "gitops_changes": "healthy",
            },
        }
    }


def test_readiness_contains_unexpected_dependency_errors(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_status",
        lambda: (_ for _ in ()).throw(RuntimeError("internal detail")),
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert "internal detail" not in response.text


def test_readiness_treats_malformed_aws_status_as_unavailable(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_status", lambda: ["connected"])

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "not_ready"
    assert response.json()["detail"]["dependencies"]["aws"] == "unhealthy"


def test_readiness_probe_is_available_without_api_credentials(monkeypatch):
    monkeypatch.setattr(
        main.aws_service,
        "get_status",
        lambda: {"status": "connected"},
    )
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"operator-token": Principal("operator", "operator", "tenant-a")},
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_fails_when_a_persistent_store_is_unavailable(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_status", lambda: {"status": "connected"})
    monkeypatch.setattr(
        main, "_sqlite_store_ready",
        lambda path: path != main.audit_trail.database_path,
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["dependencies"] == {
        "aws": "healthy",
        "audit_events": "unhealthy",
        "audit_idempotency": "healthy",
        "action_plans": "healthy",
        "gitops_changes": "healthy",
    }


def test_readiness_fails_when_action_plan_store_is_unavailable(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_status", lambda: {"status": "connected"})
    monkeypatch.setattr(
        main, "_sqlite_store_ready",
        lambda path: path != main.action_plan_store.database_path,
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["dependencies"]["action_plans"] == "unhealthy"


def test_readiness_fails_when_gitops_store_is_unavailable(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_status", lambda: {"status": "connected"})
    monkeypatch.setattr(
        main,
        "_sqlite_store_ready",
        lambda path: path != main.gitops_registry.database_path,
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["dependencies"]["gitops_changes"] == "unhealthy"


def _configure_shared_database_readiness(monkeypatch, database_url):
    monkeypatch.setattr(main.audit_trail, "database_path", database_url)
    monkeypatch.setattr(main.action_plan_store, "database_path", database_url)
    monkeypatch.setattr(main.gitops_registry, "database_path", database_url)
    monkeypatch.setattr(main, "DEFAULT_DB_PATH", database_url)


def test_readiness_probes_all_shared_persistence_stores(monkeypatch):
    database_url = "mysql+pymysql://user:secret@db.example.test:3306/cloudops"
    _configure_shared_database_readiness(monkeypatch, database_url)
    monkeypatch.setattr(main.aws_service, "get_status", lambda: {"status": "connected"})
    probed = []
    monkeypatch.setattr(
        main,
        "_shared_database_ready",
        lambda url: probed.append(url) or True,
    )

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert probed == [database_url] * 4
    assert "secret" not in response.text
    assert "db.example.test" not in response.text


def test_readiness_fails_closed_when_shared_database_is_unavailable(monkeypatch):
    database_url = "mysql+pymysql://user:secret@db.example.test:3306/cloudops"
    _configure_shared_database_readiness(monkeypatch, database_url)
    monkeypatch.setattr(main.aws_service, "get_status", lambda: {"status": "connected"})
    monkeypatch.setattr(main, "_shared_database_ready", lambda url: False)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["dependencies"] == {
        "aws": "healthy",
        "audit_events": "unhealthy",
        "audit_idempotency": "unhealthy",
        "action_plans": "unhealthy",
        "gitops_changes": "unhealthy",
    }
    assert "secret" not in response.text
    assert "db.example.test" not in response.text
