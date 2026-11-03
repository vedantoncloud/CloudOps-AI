# ADR 0011: Audit idempotency backup and restore verification

- Status: Implemented for legacy SQLite; shared SQL backups remain provider-managed.
- Date: 2026-11-03
- Related: ADR 0001, ADR 0003, ADR 0009

## Context

The audit idempotency store is one of the four persistence stores identified in ADR 0001, but the admin backup API and SQLite restore-drill utility covered only audit events, action plans, and GitOps state. This left the legacy idempotency database without the same offline recovery validation path.

## Decision

The admin-only `/autonomy/audit/database/backup/idempotency` endpoint now creates a consistent SQLite snapshot using the existing online backup API. When `CLOUDOPS_DATABASE_URL` is configured, it returns the same provider-managed backup response as the other shared stores and never tries to treat a SQL URL as a local file.

The `verify_database_backup.py` utility accepts `idempotency` as a store. It runs SQLite integrity validation, checks application-level claim counts and status consistency, and rejects malformed evidence or unknown claim states without modifying the supplied backup.

## Validation

- API tests verify admin authorization, snapshot integrity, source immutability, and provider-managed behavior for shared SQL URLs.
- Restore-drill tests verify valid idempotency snapshots and reject inconsistent claim states.
- Existing backup/restore tests for the other SQLite stores remain unchanged.

## Scope and safety

No production database is configured or migrated. Shared database backup and point-in-time recovery remain the responsibility of the configured database provider. The utility validates a local SQLite backup only; it does not import or cut over production data.
