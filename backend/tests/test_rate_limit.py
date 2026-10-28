import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from rate_limit import RateLimitMiddleware, RequestRateLimiter


def _client(limiter, tokens=None):
    app = FastAPI()
    # Middleware is wrapped in reverse registration order: authentication
    # must populate request.state before the limiter chooses an identity.
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens=tokens or {
            "alice-token": Principal("alice", "reader", "tenant-a"),
            "bob-token": Principal("bob", "reader", "tenant-a"),
        },
    )

    @app.get("/items")
    def items():
        return {"items": []}

    return TestClient(app)


def test_rate_limit_returns_429_and_retry_after_after_configured_limit():
    client = _client(RequestRateLimiter(limit=2, window_seconds=30, clock=lambda: 5))
    headers = {"Authorization": "Bearer alice-token"}

    assert client.get("/items", headers=headers).status_code == 200
    assert client.get("/items", headers=headers).status_code == 200
    limited = client.get("/items", headers=headers)

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Request rate limit exceeded"}
    assert limited.headers["retry-after"] == "25"


def test_rate_limit_is_scoped_to_authenticated_principal_and_resets_next_window():
    now = [0]
    limiter = RequestRateLimiter(limit=1, window_seconds=10, clock=lambda: now[0])
    client = _client(limiter)

    assert client.get("/items", headers={"Authorization": "Bearer alice-token"}).status_code == 200
    assert client.get("/items", headers={"Authorization": "Bearer alice-token"}).status_code == 429
    assert client.get("/items", headers={"Authorization": "Bearer bob-token"}).status_code == 200
    now[0] = 10
    assert client.get("/items", headers={"Authorization": "Bearer alice-token"}).status_code == 200


@pytest.mark.parametrize("limit,window", [(0, 10), (1, 0), (-1, 10)])
def test_rate_limiter_rejects_nonpositive_bounds(limit, window):
    with pytest.raises(ValueError, match="must be positive"):
        RequestRateLimiter(limit=limit, window_seconds=window)


def test_rate_limiter_environment_configuration_must_be_positive_integer(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_RATE_LIMIT_REQUESTS", "many")
    with pytest.raises(RuntimeError, match="CLOUDOPS_RATE_LIMIT_REQUESTS must be a positive integer"):
        RequestRateLimiter.from_environment()


def test_rate_limiter_prunes_expired_identities_at_capacity(monkeypatch):
    monkeypatch.setattr(RequestRateLimiter, "MAX_CLIENTS", 1)
    now = [0]
    limiter = RequestRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.allow("alice") == (True, 10)
    now[0] = 10
    assert limiter.allow("bob") == (True, 10)
    assert list(limiter._windows) == ["bob"]


def test_rate_limit_does_not_allow_unauthenticated_requests_through():
    client = _client(RequestRateLimiter(limit=1, window_seconds=10))

    assert client.get("/items").status_code == 401



def test_rate_limiter_bounds_new_identities_with_a_shared_overflow_bucket(monkeypatch):
    monkeypatch.setattr(RequestRateLimiter, "MAX_CLIENTS", 1)
    now = [0]
    limiter = RequestRateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])

    assert limiter.allow("alice") == (True, 10)
    # New identities share one bounded bucket once the identity map is full.
    assert limiter.allow("bob") == (True, 10)
    assert len(limiter._windows) == 1
    assert list(limiter._windows) == ["__rate_limit_overflow__"]

    assert limiter.allow("carol") == (False, 10)
    assert len(limiter._windows) == 1

    # The shared bucket resets at the next fixed-window boundary.
    now[0] = 10
    assert limiter.allow("carol") == (True, 10)
    assert len(limiter._windows) == 1
