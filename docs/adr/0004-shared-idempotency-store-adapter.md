# ADR 0004: Opt-in SQLAlchemy audit idempotency store

- Status: Implemented adapter; production enablement remains opt-in and gated.
- Date: 2026-11-03
- Related: ADR 0001, ADR 0002, ADR 0003

## Decision

The persistent audit idempotency store can now use the shared Alembic-managed schema through an explicit `database_url`. The existing SQLite path remains the default and retains its current initialization and behaviour.

For MySQL, a claim is serialized with an `INSERT ... ON DUPLICATE KEY UPDATE` against the composite `(run_id, event_type)` primary key, followed by a `SELECT ... FOR UPDATE` locking read. The claim transaction checks canonical evidence, emitted status, and lease age before returning or rotating the fencing token. Finalization updates only a pending row whose token still matches. This prevents an expired claimant from finalizing after a newer worker has reclaimed the claim.

The audit health and reconciliation readers accept the same explicit SQLAlchemy URL and remain read-only. The health and reconciliation HTTP routes resolve `CLOUDOPS_DATABASE_URL` when explicitly configured; otherwise they continue using `CLOUDOPS_AUDIT_IDEMPOTENCY_DB` and the legacy SQLite path.

## Safety and scope

- No production environment variable or secret is set by this change.
- The application continues to default to SQLite.
- A shared database must already have the Alembic schema applied; the adapter refuses to silently create or alter a shared schema.
- This change migrates only the idempotency claim store. The audit event chain, action-plan store, and GitOps store remain on their existing SQLite implementations.
- No existing data is copied or deleted, and no AWS infrastructure mutation is enabled.

## Validation

- SQLite-backed SQLAlchemy tests validate schema gating, claims, lease reclaim, fencing, health and read-only reconciliation.
- MySQL 8.4 CI tests exercise concurrent claims across independent connections, duplicate suppression, conflicting evidence, case-sensitive identifiers, stale-token fencing, health, and reconciliation.
- Existing SQLite tests continue to validate the legacy default path.
