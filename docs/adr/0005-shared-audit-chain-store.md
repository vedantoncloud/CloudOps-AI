# ADR 0005: Shared transactional audit hash chain

- Status: Implemented adapter; production enablement remains opt-in and gated.
- Date: 2026-11-03
- Related: ADR 0001, ADR 0002, ADR 0003, ADR 0004

## Decision

The persistent audit trail now supports the Alembic-managed shared schema through the same explicit `CLOUDOPS_DATABASE_URL` used by the idempotency adapter. The legacy SQLite file remains the default when no shared URL is configured.

Migration 0002 adds one `audit_chain_state` row containing the last sequence and hash. It is backfilled from the existing `audit_events` tail so an already-populated shared audit table can be adopted without resetting its chain.

Every shared append locks the singleton state row inside the same transaction as the event insert and head update. MySQL uses `SELECT ... FOR UPDATE`; the SQLAlchemy SQLite dialect uses `BEGIN IMMEDIATE`. The writer verifies that the stored head matches the current event-table tail before appending and fails closed if they diverge. Sequence assignment is explicit and the new event hash is computed from the locked previous hash.

Read, integrity-check, and verifiable-export operations continue to use the existing canonical event JSON and SHA-256 format. The existing SQLite online backup endpoint remains available for SQLite; when shared SQL storage is selected, the endpoint returns a sanitized 503 and directs backup responsibility to the configured database provider instead of attempting a misleading SQLite snapshot.

## Safety and scope

- No production database URL or credentials are configured.
- SQLite remains the default runtime.
- The shared audit chain requires Alembic migrations through head before application startup.
- No existing SQLite data is copied or deleted.
- Audit idempotency is already opt-in on the same URL; action-plan and GitOps stores remain SQLite.
- No infrastructure mutation is enabled.

## Validation

- SQLite migration tests verify migration 0002 backfills an existing audit tail.
- SQLAlchemy/SQLite tests cover append, reopen, export, concurrent appends, head mismatch rejection, and clear/reset.
- MySQL 8.4 integration tests append concurrently from independent worker engines and verify sequence order, hash continuity, and fail-closed head checks.
- Existing SQLite audit-chain and backup tests remain in the full backend suite.
