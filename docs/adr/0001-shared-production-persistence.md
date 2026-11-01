# ADR-0001: Shared production persistence

- **Status:** Proposed for staged implementation
- **Date:** 2026-11-02
- **Scope:** Audit events, audit idempotency/reconciliation, action-plan lifecycle, and GitOps change-set lifecycle

## Context

The production container currently configures four independent SQLite files:

| Store | Current configuration | Owner |
|---|---|---|
| Audit event chain | `CLOUDOPS_AUDIT_EVENTS_DB` | `PersistentAuditTrail` |
| Audit idempotency and reconciliation | `CLOUDOPS_AUDIT_IDEMPOTENCY_DB` | `PersistentAuditIdempotencyStore` |
| Action-plan lifecycle | `CLOUDOPS_ACTION_PLANS_DB_PATH` | `ActionPlanStore` |
| GitOps change-set lifecycle | `CLOUDOPS_GITOPS_DB_PATH` | `GitOpsChangeSetRegistry` |

The stores open their own SQLite connections and files. Audit records and lifecycle state are therefore committed independently: a lifecycle update and its audit event do not share one transaction. SQLite's local-file deployment model also does not provide a shared transactional database for multiple application replicas.

The current implementation has useful safety properties that must be preserved: append-only hash-chained audit events, idempotent claims with expiring leases and claim tokens, tenant ownership metadata, durable lifecycle state, startup validation, and read-only SQLite backup/restore tooling.

The pinned backend requirements already include SQLAlchemy 2.0 and PyMySQL. The inspected persistence stores do not currently use SQLAlchemy; they use the Python SQLite driver directly.

## Decision

Adopt **MySQL 8.0 or later, preferably a managed MySQL-compatible service such as Amazon RDS for MySQL**, as the target shared production persistence engine, accessed through SQLAlchemy 2.x with the already-pinned PyMySQL driver.

This is the lowest-disruption target supported by the current dependency set. It avoids introducing a second database driver and a new persistence ecosystem solely for this migration. The deployment owner must confirm that the production database service is MySQL 8.0+ compatible before the implementation phase begins. If the actual target service is PostgreSQL, revisit this ADR before writing migrations rather than silently introducing a different backend.

All four stores will ultimately use one configured SQLAlchemy engine/session boundary and one database. Store-specific tables and repository interfaces remain separate where that preserves domain boundaries, but lifecycle state changes and their corresponding audit events must be committed in a single database transaction wherever they form one logical operation.

## Required design constraints

1. **One authoritative database:** production reads and writes must use the shared database. Do not introduce permanent dual-write behavior or silently fall back to local SQLite when the shared database is unavailable.
2. **Explicit environment configuration:** production startup must fail closed when the database URL is missing, invalid, unreachable, or incompatible with the expected schema. Secrets must be injected at runtime and never committed.
3. **Migrations:** introduce versioned, repeatable schema migrations with a recorded schema revision. Startup must not perform ad-hoc destructive schema changes.
4. **Transactions:** lifecycle mutation plus its audit event must be atomic. Idempotency claim acquisition and completion must retain their lease/token compare-and-set semantics under concurrent workers.
5. **Audit-chain serialization:** concurrent appenders must serialize chain-head selection and event insertion within a transaction using a database-supported locking strategy. Hash canonicalization and existing export/verification contracts must remain stable.
6. **Tenant isolation:** tenant identifiers remain first-class columns, not only JSON payload fields. Add tenant-aware indexes and enforce tenant predicates at repository boundaries. Preserve admin/system event semantics explicitly.
7. **Uniqueness and ordering:** preserve unique action/change identifiers, unique idempotency keys, stable ordering, and deterministic pagination. Do not rely on unspecified row order.
8. **Connection lifecycle:** use bounded connection pooling, connection health checks, transaction rollback on errors, and clean shutdown. Never share a live ORM session across requests or threads.
9. **Backups and recovery:** replace SQLite-specific production backup assumptions with managed database snapshots plus documented point-in-time recovery. Keep SQLite backup/verification tools for legacy import and offline archive validation until their retirement is separately approved.
10. **No infrastructure execution changes:** this persistence migration must not enable real AWS resource mutations; dry-run-only execution remains in force.

## Migration plan

### Phase 0 — contract and deployment confirmation

- Confirm the production MySQL service/version, TLS requirements, network path, credentials delivery, backup/PITR retention, and operational owner.
- Capture current SQLite schemas, row counts, tenant distribution, audit-chain validity, idempotency pending/emitted counts, and lifecycle status counts.
- Define rollback criteria and a tested maintenance-window procedure.

### Phase 1 — persistence foundation

- Add a central SQLAlchemy engine/session factory with explicit configuration and safe pool defaults.
- Add versioned migrations for all four stores.
- Add repository-level transaction boundaries and database health/readiness reporting.
- Add integration tests against a real MySQL 8 service in CI; SQLite-only tests remain useful for legacy import and unit-level behavior but cannot establish MySQL correctness.

### Phase 2 — store-by-store adapters

- Migrate action plans and GitOps state first, preserving payload decoding and tenant metadata.
- Migrate idempotency claims next, proving concurrent claim, lease expiry, token fencing, and emitted-state behavior.
- Migrate the audit chain last, proving concurrent append serialization, hash verification, export equivalence, and append-only permissions.
- Make lifecycle mutation plus audit append atomic after the relevant stores share the transaction boundary.

### Phase 3 — verified data migration and cutover

- Take immutable, integrity-checked SQLite snapshots of all stores.
- Import into an isolated MySQL target using deterministic, resumable tooling.
- Compare counts, keys, tenant ownership, lifecycle states, idempotency states, and full audit-chain verification before cutover.
- Cut over with writes paused; perform a final delta import and validation; then switch production configuration to the shared database.
- Retain source snapshots read-only for the approved rollback/retention period. Do not run concurrent writes to both systems.

### Phase 4 — operations and retirement

- Exercise backup restore and point-in-time recovery in an isolated environment.
- Document schema upgrade, credential rotation, connection exhaustion, failover, restore, and incident procedures.
- Remove SQLite production-path configuration only after a separately reviewed retirement change confirms migration, restore, and rollback acceptance.

## Acceptance criteria

- A production instance cannot start in shared-database mode without a valid database configuration and current schema.
- Two or more application workers can safely create/approve/reject lifecycle records and claim idempotency keys without duplicate or lost transitions.
- Every committed lifecycle transition has its corresponding audit event in the same transaction; failed transactions leave neither partial state nor a success event.
- Audit-chain verification and export produce the same logical event sequence before and after migration.
- Tenant-scoped reads and writes remain isolated under concurrent integration tests.
- Restore from a production-equivalent backup is demonstrated and documented.
- No real infrastructure mutation is enabled by this work.

## Consequences

- Production deployment gains a shared transactional persistence layer suitable for multiple replicas.
- A managed MySQL service, credentials, network access, migration ownership, and database operations become explicit deployment requirements.
- The application must manage connection pools and schema migrations deliberately.
- Existing SQLite files are migration sources and offline archives, not a supported multi-replica production database.
