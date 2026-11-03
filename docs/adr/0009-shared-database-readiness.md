# ADR 0009: Shared database readiness probes

- Status: Implemented
- Date: 2026-11-03
- Related: ADR 0001, ADR 0003, ADR 0008

## Context

The readiness endpoint previously treated every persistence location as a filesystem path. With `CLOUDOPS_DATABASE_URL`, the configured value is a SQLAlchemy connection URL rather than a SQLite file, which caused a false negative for a healthy shared database.

## Decision

Readiness now uses the existing read-only SQLite probe for legacy file paths and a short-lived SQLAlchemy connection for shared database URLs. The shared probe checks connectivity, the Alembic revision table, and the required audit-event, idempotency, action-plan, GitOps, and singleton state tables. Missing schema objects or singleton rows fail readiness closed.

Readiness responses never include connection URLs, credentials, hostnames, or raw driver exceptions. Liveness remains independent of AWS and persistence; readiness continues to include AWS and all four persistence dependencies.

## Validation

- Existing SQLite readiness tests cover the legacy path.
- Shared database tests verify all four stores are probed through the configured SQLAlchemy URL.
- Unavailable shared database tests verify a 503 response without connection details.
- Full backend and MySQL 8.4 migration CI validate the deployment path.

## Scope and safety

This change does not configure a production database, create infrastructure, migrate SQLite data, or enable real AWS mutations. Production cutover remains a separate approved operation.
