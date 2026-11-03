# ADR 0006: Shared SQL action-plan persistence

- Status: Implemented adapter; production enablement remains opt-in and gated.
- Date: 2026-11-03
- Related: ADR 0001, ADR 0002, ADR 0003, ADR 0004, ADR 0005

## Decision

The action-plan store now supports the shared Alembic schema through an explicit SQLAlchemy `database_url`. The API uses `CLOUDOPS_DATABASE_URL` when configured; otherwise the existing SQLite file remains the default.

Migration 0003 adds a singleton `action_plan_state` row containing the last allocated `created_order`. The migration seeds it from the current maximum order so existing shared rows retain their relative ordering.

All shared writes lock this allocator row before reading or modifying action IDs. New plans receive monotonically increasing order values inside the same transaction as their insert. Existing plans update tenant ownership and payload without changing their original order. A batch save is one transaction, so serialization or database errors roll back every plan in the batch. MySQL uses `SELECT ... FOR UPDATE`; the SQLAlchemy SQLite dialect uses `BEGIN IMMEDIATE`.

## Safety and scope

- No production database URL or credentials are configured.
- SQLite remains the default when `CLOUDOPS_DATABASE_URL` is absent.
- Shared action-plan storage requires Alembic migrations through head before application startup.
- The SQLite backup endpoint remains supported for SQLite; shared database backups are delegated to the configured provider.
- This adapter improves durable shared writes, but the API's in-memory plan registry is still populated at startup. Cross-worker read-through/cache coherence remains a separate follow-up before multi-worker production cutover.
- No existing SQLite data is copied or deleted, and no infrastructure mutation is enabled.

## Validation

- SQLAlchemy/SQLite tests cover persistence, tenant ownership, update-order stability, batch rollback, and concurrent creation.
- MySQL 8.4 tests exercise concurrent inserts from independent store instances and verify unique ordered sequence values.
- Existing SQLite action-plan tests continue to validate the default backend.
