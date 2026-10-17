from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
import main
from observability import RequestMetrics, RequestObservabilityMiddleware


def test_request_metrics_capture_success_failures_and_route_templates():
    app = FastAPI()
    metrics = RequestMetrics()
    app.add_middleware(RequestObservabilityMiddleware, metrics=metrics)

    @app.get("/resources/{resource_id}")
    def resource(resource_id: str):
        if resource_id == "unavailable":
            raise HTTPException(status_code=503, detail="provider unavailable")
        return {"id": resource_id}

    client = TestClient(app)
    assert client.get("/resources/i-123").status_code == 200
    assert client.get("/resources/unavailable").status_code == 503

    output = metrics.prometheus_text()
    assert 'cloudops_http_requests_total{method="GET",route="/resources/{resource_id}",status="200"} 1' in output
    assert 'cloudops_http_requests_total{method="GET",route="/resources/{resource_id}",status="503"} 1' in output
    assert 'cloudops_http_request_duration_seconds_bucket{method="GET",route="/resources/{resource_id}",status="200",le="+Inf"} 1' in output
    assert "/resources/i-123" not in output
    assert "provider unavailable" not in output


def test_metrics_text_escapes_label_values_and_empty_registry_is_valid():
    metrics = RequestMetrics()
    assert metrics.prometheus_text().endswith("\n")

    metrics.observe("GET", '/items/"quoted"', 200, 0.02)
    output = metrics.prometheus_text()

    assert 'route="/items/\\"quoted\\""' in output
    assert "le=\"+Inf\"} 1" in output


def test_metrics_endpoint_uses_prometheus_content_type_and_requires_authentication():
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"reader-token": Principal("operator", "reader", "tenant-a")},
    )
    app.add_api_route("/metrics", main.metrics)
    client = TestClient(app)

    assert client.get("/metrics").status_code == 401
    response = client.get("/metrics", headers={"Authorization": "Bearer reader-token"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "cloudops_http_requests_total" in response.text
