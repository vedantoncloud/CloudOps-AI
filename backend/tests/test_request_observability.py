import json
import logging

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from observability import RequestObservabilityMiddleware


def build_app():
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/items/{item_id}")
    def get_item(item_id: str, request: Request):
        return {"item_id": item_id, "request_id": request.state.request_id}

    return app


def test_request_id_is_returned_and_logged_with_safe_route_metadata(caplog):
    caplog.set_level(logging.INFO, logger="cloudops.http")
    response = TestClient(build_app()).get(
        "/items/abc?access_token=do-not-log",
        headers={"X-Request-ID": "trace.123"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace.123"
    assert response.json()["request_id"] == "trace.123"
    record = json.loads(next(r.message for r in caplog.records if r.name == "cloudops.http"))
    assert record["event"] == "http_request"
    assert record["request_id"] == "trace.123"
    assert record["method"] == "GET"
    assert record["path"] == "/items/abc"
    assert record["status_code"] == 200
    assert record["duration_ms"] >= 0
    assert "access_token" not in json.dumps(record)


def test_invalid_request_id_is_replaced_with_generated_id():
    response = TestClient(build_app()).get("/items/abc", headers={"X-Request-ID": "bad id\r\n"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id\r\n"
    assert len(response.headers["x-request-id"]) == 36
