# ADR 0003: Shared persistence migration foundation

- Status: Proposed implementation foundation; production adoption remains gated.
- Date: 2026-11-03
- Supersedes: None

## Decision

Introduce Alembic-managed, versioned schema changes using the existing SQLAlchemy 2.x and PyMySQL stack. The first revision defines the four durable store contracts in one schema:

- `audit_events`: ordered event JSON and SHA-256 chain hash.
- `audit_idempotency`: composite `(run_id, event_type)` identity, canonical evidence, pending/emitted status, claim token, and lease timestamp.
- `action_plans`: action identity, nullable tenant ownership for legacy/global rows, serialized plan payload, and stable creation order.
- `gitops_change_sets`: change identity, nullable tenant ownership, serialized change-set payload, and stable creation order.

The schema uses InnoDB and binary UTF-8 collation on MySQL so identifiers retain SQLite's case-sensitive equality semantics. It uses bounded key columns, text payloads, and indexes for tenant-scoped ordered reads and pending-claim inspection. The migration framework is tested against SQLite, while the application continues using its existing four SQLite stores.

## Safety boundary

This change does not configure a production database URL, migrate data, switch runtime stores, remove SQLite backup/restore paths, or enable infrastructure mutations. Migrations require an explicit `CLOUDOPS_DATABASE_URL`; no implicit production database is selected.

Before any production cutover, the operator must confirm the managed database service/version, network reachability, TLS policy, credential delivery, backup/PITR ownership, restore rehearsal, maintenance window, and rollback procedure. The existing source contracts and cross-worker consistency gaps recorded in ADR 0002 remain implementation requirements; this schema is not proof that those behaviours have been ported.

## Validation

- CI runs an SQLite upgrade/downgrade test for fast deterministic migration coverage.
- CI also starts MySQL 8.4 and runs the initial revision against the production-target dialect.
- The migration smoke test verifies all four tables and critical columns, then verifies downgrade removes the new schema.
- Runtime persistence and existing SQLite backup endpoints remain unchanged until a separately reviewed store-adapter migration is ready.
