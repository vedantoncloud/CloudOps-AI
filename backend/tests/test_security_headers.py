import asyncio

from security_headers import SecurityHeadersMiddleware


def run_middleware(*, scope_type="http", scheme="http", headers=None):
    sent = []
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": headers or [],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": scope_type,
        "scheme": scheme,
        "method": "GET",
        "path": "/",
        "headers": [],
    }
    asyncio.run(SecurityHeadersMiddleware(app)(scope, receive, send))
    return called, sent


def response_headers(messages):
    return dict(messages[0]["headers"])


def test_http_responses_include_default_browser_security_headers():
    called, messages = run_middleware(scheme="http")

    assert called is True
    headers = response_headers(messages)
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"referrer-policy"] == b"strict-origin-when-cross-origin"
    assert headers[b"permissions-policy"] == b"camera=(), microphone=(), geolocation=()"
    assert headers[b"cross-origin-resource-policy"] == b"same-origin"
    assert headers[b"cache-control"] == b"no-store"
    assert b"strict-transport-security" not in headers


def test_https_responses_include_hsts():
    _, messages = run_middleware(scheme="https")

    assert response_headers(messages)[b"strict-transport-security"] == b"max-age=31536000"


def test_existing_route_security_headers_are_not_overwritten():
    existing = [
        (b"cache-control", b"private, max-age=60"),
        (b"x-frame-options", b"SAMEORIGIN"),
        (b"x-custom-header", b"preserved"),
    ]

    _, messages = run_middleware(headers=existing)
    headers = response_headers(messages)

    assert headers[b"cache-control"] == b"private, max-age=60"
    assert headers[b"x-frame-options"] == b"SAMEORIGIN"
    assert headers[b"x-custom-header"] == b"preserved"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_non_http_asgi_scopes_are_passed_through_unchanged():
    called = False
    sent = []

    async def app(scope, receive, send):
        nonlocal called
        called = True
        await send({"type": "lifespan.startup.complete"})

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        sent.append(message)

    asyncio.run(
        SecurityHeadersMiddleware(app)(
            {"type": "lifespan"},
            receive,
            send,
        )
    )

    assert called is True
    assert sent == [{"type": "lifespan.startup.complete"}]
