import pytest
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse
from fastapi.testclient import TestClient

from request_limits import RequestSizeLimitMiddleware, ResponseSizeLimitMiddleware


def build_app(limit=8):
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=limit)

    @app.post("/echo")
    async def echo(request: Request):
        return {"body": (await request.body()).decode()}

    return app


def test_extremely_large_declared_content_length_returns_413_without_integer_overflow():
    import asyncio

    sent = []
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def run():
        middleware = RequestSizeLimitMiddleware(app, max_bytes=8)
        await middleware(
            {"type": "http", "method": "POST", "path": "/", "headers": [(b"content-length", b"9" * 5000)]},
            receive,
            send,
        )

    asyncio.run(run())

    assert called is False
    assert sent[0]["status"] == 413

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


def build_response_app(limit=16):
    app = FastAPI()
    app.add_middleware(ResponseSizeLimitMiddleware, max_bytes=limit)

    @app.get("/small")
    def small():
        return {"value": "1234"}

    @app.get("/large")
    def large():
        return {"value": "123456789"}

    @app.get("/stream")
    def stream():
        return StreamingResponse(iter([b"1234567890", b"abcdefghij"]))

    return app


def test_response_at_limit_is_returned_unchanged():
    app = FastAPI()
    app.add_middleware(ResponseSizeLimitMiddleware, max_bytes=8)

    @app.get("/exact")
    def exact():
        return "123456"  # JSON string encoding occupies exactly eight bytes.

    response = TestClient(app).get("/exact")

    assert response.status_code == 200
    assert response.content == b'"123456"'


def test_small_response_is_returned_unchanged():
    response = TestClient(build_response_app()).get("/small")

    assert response.status_code == 200
    assert response.json() == {"value": "1234"}


@pytest.mark.parametrize("path", ["/large", "/stream"])
def test_oversized_buffered_or_streamed_response_is_replaced(path):
    response = TestClient(build_response_app()).get(path)

    assert response.status_code == 500
    assert response.json() == {"detail": "Response exceeds the configured size limit"}
    assert int(response.headers["content-length"]) == len(response.content)


def test_response_limit_configuration_must_be_positive(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_MAX_RESPONSE_BYTES", "0")

    with pytest.raises(RuntimeError, match="CLOUDOPS_MAX_RESPONSE_BYTES must be a positive integer"):
        ResponseSizeLimitMiddleware(lambda *_: None)


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"4"), (b"content-length", b"8")],
        [(b"content-length", b"invalid")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"+1")],
        [(b"content-length", b"1_0")],
        [(b"content-length", b"4"), (b"transfer-encoding", b"chunked")],
    ],
)
def test_ambiguous_or_invalid_content_length_is_rejected_before_handler(headers):
    import asyncio

    called = False
    sent = []

    async def app(scope, receive, send):
        nonlocal called
        called = True

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def run():
        middleware = RequestSizeLimitMiddleware(app, max_bytes=8)
        await middleware(
            {"type": "http", "method": "POST", "path": "/", "headers": headers},
            receive,
            send,
        )

    asyncio.run(run())

    assert called is False
    assert sent[0]["status"] == 400
    assert b"Invalid or ambiguous Content-Length" in sent[1]["body"]
