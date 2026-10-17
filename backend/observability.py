"""Request correlation and low-risk structured HTTP access logs."""

import json
import logging
import re
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_logger = logging.getLogger("cloudops.http")


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID and log one sanitized JSON record per request."""

    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if _REQUEST_ID.fullmatch(supplied_id) else str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            _logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
