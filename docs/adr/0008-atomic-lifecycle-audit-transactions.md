# ADR 0008: Atomic shared lifecycle and audit transactions

- Status: Implemented for shared action-plan and GitOps writes; legacy SQLite multi-file mode remains non-atomic.
- Date: 2026-11-03
- Related: ADR 0001 through ADR 0007

## Decision

The shared `PersistentAuditTrail` exposes `record_with_connection`, which appends a canonical SHA-256 event using a caller-owned SQLAlchemy connection without opening or committing a nested transaction. It verifies that the caller connection and audit trail target the same database URL and uses the existing audit-chain head lock.

The shared action-plan store accepts audit events as part of `save_many`. Plan inserts/updates, creation-order allocation, and corresponding audit events now commit in one database transaction. An invalid audit event rolls back the entire batch.

The shared GitOps registry similarly appends registration, approval, rejection, apply, and verification events inside the same transaction as the corresponding change-set write. Audit append failure rolls back the state transition. Existing compare-and-swap and tenant checks remain in place.

When either store is using legacy SQLite-file mode, or an in-memory audit trail is supplied, the existing fallback still records audit separately. The API's shared deployment path uses the same explicit `CLOUDOPS_DATABASE_URL` for both state and audit storage, enabling the atomic path.

## Safety and scope

- No production database URL or credentials are configured.
- SQLite remains the default; its separate audit and state files cannot participate in one transaction.
- Shared atomic writes require Alembic migrations through head and a single matching database URL.
- The audit chain head lock is acquired within the lifecycle transaction; failed audit validation rolls back both the audit and lifecycle writes.
- This change does not migrate existing SQLite data or enable real AWS infrastructure mutations.
- Audit export/backup for shared SQL remains provider-managed; the SQLite snapshot endpoint does not attempt to snapshot MySQL.

## Validation

- SQLite/SQLAlchemy tests prove action-plan save and audit append commit together, and invalid audit append rolls back the plan and allocator.
- SQLite/SQLAlchemy tests prove GitOps registration and transition audit append commit together, and failed audit validation rolls back the state transition.
- MySQL 8.4 integration tests repeat the atomic commit/rollback contracts against independent SQLAlchemy engines.
- Existing legacy SQLite tests remain in the full backend suite.
