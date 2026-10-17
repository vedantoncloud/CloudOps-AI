import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from request_limits import RequestSizeLimitMiddleware


def build_app(limit=8):
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=limit)

    @app.post("/echo")
    async def echo(request: Request):
        return {"body": (await request.body()).decode()}

    return app


def test_request_body_at_limit_reaches_handler():
    response = TestClient(build_app()).post("/echo", content=b"12345678")

    assert response.status_code == 200
    assert response.json() == {"body": "12345678"}


def test_declared_oversized_request_is_rejected_before_handler():
    response = TestClient(build_app()).post(
        "/echo", content=b"123456789", headers={"content-length": "9"}
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the 8-byte limit"}


def test_streamed_request_without_content_length_is_still_bounded():
    def body_stream():
        yield b"1234"
        yield b"56789"

    response = TestClient(build_app()).post("/echo", content=body_stream())

    assert response.status_code == 413
    assert response.json()["detail"].startswith("Request body exceeds")


def test_request_limit_configuration_must_be_positive(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_MAX_REQUEST_BYTES", "0")

    with pytest.raises(RuntimeError, match="CLOUDOPS_MAX_REQUEST_BYTES must be a positive integer"):
        RequestSizeLimitMiddleware(lambda *_: None)
