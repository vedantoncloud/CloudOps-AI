"""Bounded per-process request limiting for the assembled API."""

import os
import threading
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


class RequestRateLimiter:
    """Fixed-window limiter keyed by authenticated principal or client address."""

    MAX_CLIENTS = 10000

    def __init__(self, limit: int = 120, window_seconds: int = 60, clock=None):
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not isinstance(window_seconds, int)
            or isinstance(window_seconds, bool)
            or limit <= 0
            or window_seconds <= 0
        ):
            raise ValueError("limit and window_seconds must be positive integers")
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._windows: OrderedDict[str, tuple[int, int]] = OrderedDict()

    @classmethod
    def from_environment(cls):
        limit = _positive_int(os.getenv("CLOUDOPS_RATE_LIMIT_REQUESTS", "120"), "CLOUDOPS_RATE_LIMIT_REQUESTS")
        window = _positive_int(os.getenv("CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS", "60"), "CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS")
        return cls(limit, window)

    def allow(self, key: str) -> tuple[bool, int]:
        now = self.clock()
        window = int(now // self.window_seconds)
        reset_in = max(1, int((window + 1) * self.window_seconds - now + 0.999))
        with self._lock:
            if len(self._windows) >= self.MAX_CLIENTS:
                for existing, (period, _) in list(self._windows.items()):
                    if period < window:
                        del self._windows[existing]
            current_window, count = self._windows.get(key, (window, 0))
            if current_window != window:
                count = 0
            if count >= self.limit:
                self._windows.move_to_end(key)
                return False, reset_in
            if key not in self._windows and len(self._windows) >= self.MAX_CLIENTS:
                # Avoid unbounded state growth. Unknown identities share an
                # overflow bucket until the next window expires old entries.
                key = "__rate_limit_overflow__"
                current_window, count = self._windows.get(key, (window, 0))
                if current_window != window:
                    count = 0
                if count >= self.limit:
                    return False, reset_in
            self._windows[key] = (window, count + 1)
            self._windows.move_to_end(key)
            return True, reset_in


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RequestRateLimiter | None = None):
        super().__init__(app)
        self.limiter = limiter or RequestRateLimiter.from_environment()

    async def dispatch(self, request: Request, call_next):
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            key = f"principal:{getattr(request.state, 'tenant_id', '')}:{principal.subject}"
        else:
            client = request.client.host if request.client else "unknown"
            key = f"address:{client}"
        allowed, retry_after = self.limiter.allow(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Request rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)
