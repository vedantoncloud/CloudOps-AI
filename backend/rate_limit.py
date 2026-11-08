"""Bounded per-process and shared SQL request limiting."""
import hashlib
import os
import threading
import time
from collections import OrderedDict

from sqlalchemy import BigInteger, Column, Integer, MetaData, String, Table, case, create_engine, delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _positive_int(value: str, name: str) -> int:
    if not isinstance(value, str) or not value or any(c < "0" or c > "9" for c in value):
        raise RuntimeError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return parsed


class RequestRateLimiter:
    """Fixed-window limiter keyed by authenticated principal or client address."""
    MAX_CLIENTS = 10000

    def __init__(self, limit: int = 120, window_seconds: int = 60, clock=None):
        if (not isinstance(limit, int) or isinstance(limit, bool) or
            not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or
            limit <= 0 or window_seconds <= 0):
            raise ValueError("limit and window_seconds must be positive integers")
        self.limit, self.window_seconds = limit, window_seconds
        self.clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._windows: OrderedDict[str, tuple[int, int]] = OrderedDict()

    @classmethod
    def from_environment(cls):
        limit = _positive_int(os.getenv("CLOUDOPS_RATE_LIMIT_REQUESTS", "120"), "CLOUDOPS_RATE_LIMIT_REQUESTS")
        window = _positive_int(os.getenv("CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS", "60"), "CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS")
        database_url = os.getenv("CLOUDOPS_DATABASE_URL")
        return SharedSQLRequestRateLimiter(limit, window, database_url) if database_url else cls(limit, window)

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
                key = "__rate_limit_overflow__"
                current_window, count = self._windows.get(key, (window, 0))
                if current_window != window:
                    count = 0
                if count >= self.limit:
                    return False, reset_in
            self._windows[key] = (window, count + 1)
            self._windows.move_to_end(key)
            return True, reset_in


class SharedSQLRequestRateLimiter:
    """Atomic fixed-window counters shared by workers using one SQL database."""
    CLEANUP_INTERVAL = 100

    def __init__(self, limit: int, window_seconds: int, database_url: str, clock=None):
        if (not isinstance(limit, int) or isinstance(limit, bool) or
            not isinstance(window_seconds, int) or isinstance(window_seconds, bool) or
            limit <= 0 or window_seconds <= 0):
            raise ValueError("limit and window_seconds must be positive integers")
        if not isinstance(database_url, str) or not database_url.startswith(("mysql+pymysql://", "sqlite:///")):
            raise ValueError("shared rate limiting requires mysql+pymysql or sqlite")
        self.limit, self.window_seconds = limit, window_seconds
        self.clock = clock or time.time
        self._engine = create_engine(database_url, pool_pre_ping=True, future=True)
        self._cleanup_lock = threading.Lock()
        self._requests_since_cleanup = 0
        self._table = Table(
            "rate_limit_counters", MetaData(),
            Column("bucket_key", String(64), primary_key=True),
            Column("window_number", BigInteger, nullable=False),
            Column("request_count", Integer, nullable=False),
            Column("updated_at", BigInteger, nullable=False),
        )
        try:
            with self._engine.connect() as connection:
                connection.execute(select(self._table.c.bucket_key).limit(0))
        except SQLAlchemyError as exc:
            self._engine.dispose()
            raise RuntimeError("Shared rate-limit schema is unavailable; apply the CloudOps Alembic migrations") from exc

    @staticmethod
    def _bucket_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _cleanup_if_due(self, window: int) -> None:
        with self._cleanup_lock:
            self._requests_since_cleanup += 1
            if self._requests_since_cleanup < self.CLEANUP_INTERVAL:
                return
            self._requests_since_cleanup = 0
        with self._engine.begin() as connection:
            connection.execute(delete(self._table).where(self._table.c.window_number < window - 1))

    def allow(self, key: str) -> tuple[bool, int]:
        now = self.clock()
        window = int(now // self.window_seconds)
        retry_after = max(1, int((window + 1) * self.window_seconds - now + 0.999))
        bucket, updated_at = self._bucket_key(key), int(now)
        try:
            with self._engine.begin() as connection:
                if self._engine.dialect.name == "sqlite":
                    stmt = sqlite_insert(self._table).values(
                        bucket_key=bucket, window_number=window, request_count=1, updated_at=updated_at
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[self._table.c.bucket_key],
                        set_={
                            "window_number": stmt.excluded.window_number,
                            "request_count": case(
                                (self._table.c.window_number == stmt.excluded.window_number,
                                 self._table.c.request_count + 1),
                                else_=1,
                            ),
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    count = connection.execute(stmt.returning(self._table.c.request_count)).scalar_one()
                elif self._engine.dialect.name == "mysql":
                    stmt = mysql_insert(self._table).values(
                        bucket_key=bucket, window_number=window, request_count=1, updated_at=updated_at
                    )
                    stmt = stmt.on_duplicate_key_update(
                        window_number=stmt.inserted.window_number,
                        request_count=case(
                            (self._table.c.window_number == stmt.inserted.window_number,
                             self._table.c.request_count + 1),
                            else_=1,
                        ),
                        updated_at=stmt.inserted.updated_at,
                    )
                    connection.execute(stmt)
                    count = connection.execute(
                        select(self._table.c.request_count).where(self._table.c.bucket_key == bucket)
                    ).scalar_one()
                else:
                    raise RuntimeError("Unsupported shared rate-limit database dialect")
            self._cleanup_if_due(window)
        except (SQLAlchemyError, OSError) as exc:
            raise RuntimeError("Shared request rate limiting is unavailable") from exc
        return count <= self.limit, retry_after

    def close(self) -> None:
        self._engine.dispose()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter=None):
        super().__init__(app)
        self.limiter = limiter or RequestRateLimiter.from_environment()

    async def dispatch(self, request: Request, call_next):
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            tenant_id = getattr(request.state, "tenant_id", "")
            subject = principal.subject
            key = f"principal:{len(tenant_id)}:{tenant_id}:{len(subject)}:{subject}"
        else:
            client = request.client.host if request.client else "unknown"
            key = f"address:{client}"
        if isinstance(self.limiter, SharedSQLRequestRateLimiter):
            try:
                allowed, retry_after = await run_in_threadpool(self.limiter.allow, key)
            except RuntimeError:
                return JSONResponse(status_code=503,
                    content={"detail": "Request rate limiting is temporarily unavailable"},
                    headers={"Retry-After": "1"})
        else:
            allowed, retry_after = self.limiter.allow(key)
        if not allowed:
            return JSONResponse(status_code=429,
                content={"detail": "Request rate limit exceeded"},
                headers={"Retry-After": str(retry_after)})
        return await call_next(request)
