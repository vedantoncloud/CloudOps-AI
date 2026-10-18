from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from observability import RequestMetrics, RequestObservabilityMiddleware


def test_failure_snapshot_includes_only_server_errors_with_bounded_routes():
    app = FastAPI()
    metrics = RequestMetrics()
    app.add_middleware(RequestObservabilityMiddleware, metrics=metrics)

    @app.get("/resources/{resource_id}")
    def resource(resource_id: str):
        if resource_id == "unavailable":
            raise HTTPException(status_code=503, detail="sensitive provider response")
        if resource_id == "invalid":
            raise HTTPException(status_code=400, detail="invalid")
        return {"id": resource_id}

    client = TestClient(app)
    assert client.get("/resources/healthy").status_code == 200
    assert client.get("/resources/invalid").status_code == 400
    assert client.get("/resources/unavailable").status_code == 503

    result = metrics.failure_snapshot()
    assert result == {
        "scope": "since_process_start",
        "total": 1,
        "failures": [
            {"method": "GET", "route": "/resources/{resource_id}", "status": 503, "count": 1}
        ],
    }
    assert "sensitive provider response" not in str(result)
    assert "unavailable" not in str(result)


def test_failure_endpoint_is_admin_only_and_returns_empty_summary(monkeypatch):
    import main

    app = FastAPI()
    metrics = RequestMetrics()
    app.add_middleware(RequestObservabilityMiddleware, metrics=metrics)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={
            "reader": Principal("reader", "reader", "tenant-a"),
            "admin": Principal("admin", "admin", "tenant-a"),
        },
    )

    monkeypatch.setattr(
        main.request_metrics,
        "failure_snapshot",
        lambda: {"scope": "since_process_start", "total": 0, "failures": []},
    )
    app.add_api_route("/operations/failures", main.operation_failures)

    client = TestClient(app)
    assert client.get("/operations/failures", headers={"Authorization": "Bearer reader"}).status_code == 403
    response = client.get("/operations/failures", headers={"Authorization": "Bearer admin"})
    assert response.status_code == 200
    assert response.json() == {"scope": "since_process_start", "total": 0, "failures": []}
