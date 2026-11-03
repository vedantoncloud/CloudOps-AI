# ADR 0010: Atomic idempotency and audit finalization

- Status: Implemented for shared SQL storage; legacy SQLite-file mode retains its existing sequence.
- Date: 2026-11-03
- Related: ADR 0001, ADR 0003, ADR 0008

## Context

The persistent failure-audit bridge previously acquired an idempotency claim, appended an audit event, and marked the claim emitted in three independent transactions. A process crash after the audit append but before claim finalization could leave a pending claim. Once its lease expired, another worker could reclaim it and append the same logical event again.

## Decision

When the idempotency store and audit trail use the same shared SQL database, the bridge now locks and validates the pending claim token, appends the hash-chained audit event through the caller-owned connection, and changes the claim to emitted in one transaction.

MySQL uses a row lock on the idempotency key and the audit chain-head lock. The shared SQLite SQLAlchemy test backend uses `BEGIN IMMEDIATE`. A stale token cannot append an event or finalize a newer worker's claim. If audit validation or append fails, the transaction rolls back and the claim remains pending for lease-based recovery.

Legacy SQLite-file and in-memory configurations preserve their existing compatibility path. No cross-file atomicity is claimed for those configurations.

## Validation

- Shared SQLite integration tests cover successful finalization, duplicate suppression, append-failure rollback, retry after lease expiry, and stale-token fencing.
- MySQL 8.4 integration tests exercise the same transaction contract using the real shared schema.
- Existing claim lease, evidence-conflict, concurrency, and audit-chain tests remain in the CI suites.

## Scope and safety

No production database URL or credentials are configured. This change does not migrate existing data, change claim lease policy, or enable real AWS infrastructure mutations. Production cutover remains a separately approved operation.
