"""Request correlation and low-risk structured HTTP access logs."""

import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_logger = logging.getLogger("cloudops.http")
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_KNOWN_METHODS = {
    "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"
}


class RequestMetrics:
    """Thread-safe in-process request counters and latency histogram."""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {}
        self._durations = {}

    def observe(self, method: str, route: str, status_code: int, duration: float):
        method = method if method in _KNOWN_METHODS else "OTHER"
        key = (method, route, status_code)
        with self._lock:
            self._requests[key] = self._requests.get(key, 0) + 1
            summary = self._durations.setdefault(
                key, [0] * len(_LATENCY_BUCKETS) + [0, 0.0]
            )
            for index, bound in enumerate(_LATENCY_BUCKETS):
                if duration <= bound:
                    summary[index] += 1
            summary[-2] += 1
            summary[-1] += duration

    def prometheus_text(self) -> str:
        """Render a Prometheus text exposition snapshot."""
        with self._lock:
            requests = dict(self._requests)
            durations = {key: list(values) for key, values in self._durations.items()}

        lines = [
            "# HELP cloudops_http_requests_total Total completed HTTP requests.",
            "# TYPE cloudops_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(requests.items()):
            labels = _format_labels(method, route, status)
            lines.append(f"cloudops_http_requests_total{labels} {count}")
        lines.extend(
            (
                "# HELP cloudops_http_request_duration_seconds HTTP request duration in seconds.",
                "# TYPE cloudops_http_request_duration_seconds histogram",
            )
        )
        for key in sorted(durations):
            method, route, status = key
            summary = durations[key]
            for index, bound in enumerate(_LATENCY_BUCKETS):
                labels = _format_labels(method, route, status, le=_float_label(bound))
                lines.append(
                    f"cloudops_http_request_duration_seconds_bucket{labels} {summary[index]}"
                )
            labels = _format_labels(method, route, status, le="+Inf")
            lines.append(f"cloudops_http_request_duration_seconds_bucket{labels} {summary[-2]}")
            base = _format_labels(method, route, status)
            lines.append(f"cloudops_http_request_duration_seconds_sum{base} {summary[-1]:.9g}")
            lines.append(f"cloudops_http_request_duration_seconds_count{base} {summary[-2]}")
        return "\n".join(lines) + "\n"

    def failure_snapshot(self) -> dict:
        """Return cumulative server-error counts grouped by bounded route labels."""
        with self._lock:
            failures = [
                {"method": method, "route": route, "status": status, "count": count}
                for (method, route, status), count in self._requests.items()
                if status >= 500
            ]
        return {
            "scope": "since_process_start",
            "total": sum(item["count"] for item in failures),
            "failures": sorted(
                failures,
                key=lambda item: (-item["count"], item["route"], item["status"]),
            ),
        }


class OperationMetrics:
    """Bounded counters for named operations, without error payloads."""

    def __init__(self, include_successes: bool = False):
        self._lock = threading.Lock()
        self._failures = {}
        self._calls = {}
        self._include_successes = include_successes

    def observe(self, operation: str, failed: bool):
        with self._lock:
            self._calls[operation] = self._calls.get(operation, 0) + 1
            if failed:
                self._failures[operation] = self._failures.get(operation, 0) + 1

    def failure_snapshot(self) -> dict:
        with self._lock:
            failures = dict(self._failures)
            calls = dict(self._calls)
        return {
            "scope": "since_process_start",
            "total_failures": sum(failures.values()),
            "operations": [
                {"operation": operation, "calls": calls[operation], "failures": count}
                for operation in sorted(calls if self._include_successes else failures)
                for count in (failures.get(operation, 0),)
            ],
        }


def _float_label(value: float) -> str:
    return str(value)


def _format_labels(method: str, route: str, status: int, **extra: str) -> str:
    labels = {"method": method, "route": route, "status": str(status), **extra}
    def escape_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    rendered = ",".join(
        f'{name}="{escape_label(value)}"'
        for name, value in labels.items()
    )
    return "{" + rendered + "}"


request_metrics = RequestMetrics()
aws_operation_metrics = OperationMetrics()
database_operation_metrics = OperationMetrics(include_successes=True)


@contextmanager
def observed_sqlite_connection(connect, operation: str):
    """Count completed store operations and SQLite failures without details."""
    failed = False
    connection = None
    try:
        connection = connect()
        with connection:
            yield connection
    except sqlite3.Error:
        failed = True
        raise
    finally:
        try:
            if connection is not None:
                connection.close()
        except sqlite3.Error:
            failed = True
            raise
        finally:
            # Record the attempt even if connection cleanup itself fails.
            database_operation_metrics.observe(operation, failed)


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID and log one sanitized JSON record per request."""

    def __init__(self, app, metrics: RequestMetrics | None = None):
        super().__init__(app)
        self.metrics = metrics or request_metrics

    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if _REQUEST_ID.fullmatch(supplied_id) else str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        method = request.method if request.method in _KNOWN_METHODS else "OTHER"
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", "<unmatched>")
            self.metrics.observe(
                method,
                route,
                status_code,
                time.perf_counter() - started,
            )
            _logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": method,
                        # Log the route template, not resource identifiers from the URL.
                        "path": route,
                        "status_code": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
