# Shared distributed request rate limiting

When `CLOUDOPS_DATABASE_URL` is not configured, CloudOps AI retains its bounded
in-memory fixed-window limiter. When the shared SQL persistence URL is configured,
the API automatically uses the shared `rate_limit_counters` table so all API
workers using that database enforce the same per-identity budget.

Apply Alembic migrations before starting the application:

```sh
CLOUDOPS_DATABASE_URL='mysql+pymysql://...' alembic -c backend/alembic.ini upgrade head
```

Configure the same URL on every API replica. Supported shared backends are MySQL
through PyMySQL and SQLite. SQLite coordinates processes sharing one local
database file; it is not a network database for separate hosts.

The shared limiter uses atomic database upserts and wall-clock-aligned fixed
windows. Keep host clocks synchronized. The existing
`CLOUDOPS_RATE_LIMIT_REQUESTS` and `CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS`
settings continue to apply. Counter keys are SHA-256 digests; raw tenant IDs,
subjects, and client addresses are not stored. Expired rows are pruned
periodically.

If shared limiting is configured but the migration or database is unavailable,
requests receive HTTP 503 rather than silently falling back to independent
per-process counters. Requests exceeding the configured budget receive HTTP 429
with `Retry-After`.

This remains a fixed-window policy. Limits apply independently to authenticated
tenant/principal identities; unauthenticated requests are keyed by client
address. Monitor the shared database as part of the persistence deployment.
