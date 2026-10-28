"""Bound request bodies before API handlers parse or retain them."""

import os

from starlette.responses import JSONResponse


DEFAULT_MAX_REQUEST_BYTES = 1_048_576
DEFAULT_MAX_RESPONSE_BYTES = 4_194_304


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


class RequestSizeLimitMiddleware:
    """Reject oversized or ambiguous declared bodies and bound streamed bodies."""

    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        if max_bytes is None:
            max_bytes = _positive_int(
                os.getenv("CLOUDOPS_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES)),
                "CLOUDOPS_MAX_REQUEST_BYTES",
            )
        if max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = [(key.lower(), value) for key, value in scope.get("headers", [])]
        content_lengths = [value for key, value in raw_headers if key == b"content-length"]
        transfer_encodings = [value for key, value in raw_headers if key == b"transfer-encoding"]
        # Conflicting framing metadata can be interpreted differently by
        # upstream servers and application middleware. Reject it at the edge.
        if transfer_encodings and content_lengths:
            await self._bad_request(scope, receive, send)
            return
        if len(content_lengths) > 1:
            await self._bad_request(scope, receive, send)
            return
        if content_lengths:
            try:
                declared_size = int(content_lengths[0])
            except (TypeError, ValueError):
                await self._bad_request(scope, receive, send)
                return
            if declared_size < 0:
                await self._bad_request(scope, receive, send)
                return
            if declared_size > self.max_bytes:
                await self._too_large(scope, receive, send)
                return

        # Buffer at most the configured limit. This also enforces the cap for
        # chunked requests that do not declare Content-Length.
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._too_large(scope, receive, send)
                return
            body.extend(chunk)
            more_body = message.get("more_body", False)

        sent = False

        async def replay_body():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_body, send)

    async def _bad_request(self, scope, receive, send):
        response = JSONResponse(
            status_code=400,
            content={"detail": "Invalid or ambiguous Content-Length header"},
        )
        await response(scope, receive, send)

    async def _too_large(self, scope, receive, send):
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {self.max_bytes}-byte limit"},
        )
        await response(scope, receive, send)


class ResponseSizeLimitMiddleware:
    """Bound buffered HTTP responses and replace oversized bodies consistently."""

    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        if max_bytes is None:
            max_bytes = _positive_int(
                os.getenv("CLOUDOPS_MAX_RESPONSE_BYTES", str(DEFAULT_MAX_RESPONSE_BYTES)),
                "CLOUDOPS_MAX_RESPONSE_BYTES",
            )
        if max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        messages = []
        size = 0
        oversized = False

        async def capture(message):
            nonlocal size, oversized
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if size > self.max_bytes:
                    oversized = True
                    return
            if not oversized:
                messages.append(message)

        await self.app(scope, receive, capture)
        if oversized:
            body = b'{"detail":"Response exceeds the configured size limit"}'
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        for message in messages:
            await send(message)
