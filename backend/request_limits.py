"""Bound request bodies before API handlers parse or retain them."""

import os

from starlette.responses import JSONResponse


DEFAULT_MAX_REQUEST_BYTES = 1_048_576


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


class RequestSizeLimitMiddleware:
    """Reject oversized declared or streamed bodies with a stable 413 response."""

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

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > self.max_bytes:
                await self._too_large(scope, receive, send)
                return

        # Buffer at most the configured limit plus one byte. This also enforces
        # the cap for chunked requests that do not declare Content-Length.
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

    async def _too_large(self, scope, receive, send):
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {self.max_bytes}-byte limit"},
        )
        await response(scope, receive, send)
