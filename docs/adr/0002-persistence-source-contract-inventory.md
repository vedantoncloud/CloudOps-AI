# Persistence source-contract inventory

- **Status:** Implementation input; no production behavior changed
- **Date:** 2026-11-02
- **Related decision:** [ADR-0001: Shared production persistence](./0001-shared-production-persistence.md)
- **Scope:** Existing SQLite persistence contracts to preserve during the shared-database migration

This inventory records behavior observed in the current source and tests. It is not a schema migration and does not authorize a production database cutover.

## Current store contracts

| Store | Table and key | Persisted representation | Read/write behavior |
|---|---|---|---|
| Audit events | `audit_events`; auto-increment `sequence` | Canonical serialized `AuditEvent` JSON plus SHA-256 `event_hash` | Append uses `BEGIN IMMEDIATE`, reads the previous hash, then inserts the next event. Reads and exports are ordered by sequence. |
| Audit idempotency | `audit_idempotency`; composite primary key `(run_id, event_type)` | `evidence_json`, status, claim token, claim timestamp | Claim creates a pending lease, rejects conflicting evidence, skips emitted or active claims, and reclaims expired pending claims with a new token. Completion is a compare-and-set on key, pending status, and token. |
| Action plans | `action_plans`; primary key `action_id` | Tenant ID column, JSON plan payload, creation order | Each operation opens a connection. Batch saves are transactional; updates preserve existing creation order. Reads sort by creation order. |
| GitOps change sets | `gitops_change_sets`; primary key `change_id` | JSON manifest payload and creation order | Registry loads all rows into an in-memory dictionary at startup. Mutations persist a payload and then append an audit event separately. |

## Migration invariants

### Audit event chain

- Preserve canonical event serialization, event field values, SHA-256 calculation, genesis hash, and export format `cloudops-audit-chain-v1`.
- Preserve strictly ordered, append-only sequence semantics and first-invalid-event diagnostics.
- Replace process-local locking plus SQLite's `BEGIN IMMEDIATE` with a database-level serialization strategy that is correct across independent application workers.
- A concurrent append test must prove there is one unbroken chain, with no duplicate sequence values or forks.
- Keep verification and offline export byte/logical compatibility covered by fixtures from the legacy SQLite implementation.

### Idempotency claims

- Preserve the unique logical key `(run_id, event_type)` unless a separately reviewed compatibility change establishes a tenant-qualified key.
- Preserve normalized evidence comparison, pending/emitted states, lease expiry, and token fencing.
- A stale claimant must not be able to mark a claim emitted after another worker has reclaimed it with a newer token.
- Add multi-connection integration tests for simultaneous first claims, active-lease skips, expiry/reclaim, conflicting evidence, and stale-token completion.
- Review whether run IDs are globally unique across tenants before adding tenant_id to the key. Existing evidence JSON may carry tenant context, but the current relational key does not.

### Action plans

- Keep `tenant_id` as a first-class relational column and enforce tenant predicates in repository methods, not only in API handlers.
- Preserve the JSON payload decoder's legacy behavior, including payloads without `created_at`.
- Preserve all-or-nothing `save_many` behavior and stable creation ordering when an existing action is updated.
- Define deterministic ordering with a unique tie-breaker before introducing paginated reads.

### GitOps change sets

- Preserve manifest fields, status transitions, metadata (including tenant ownership), and duplicate-registration rejection.
- The current registry's in-memory dictionary is loaded once at startup; a shared database alone will not make reads coherent across multiple workers. The migrated repository must read authoritative state from the database or implement an explicit, tested cache invalidation protocol.
- Persisting a lifecycle state change and recording its audit event must become one transaction. Today they are separate operations, so an audit failure can leave the durable GitOps state changed without its matching event.
- Add multi-worker tests for concurrent approval/rejection and stale-state prevention.

## Cross-store transactional boundary

The target design must expose a unit-of-work boundary that can include:

1. the relevant action-plan or GitOps state transition;
2. its corresponding audit-chain append; and
3. any associated idempotency claim completion where that is part of the same logical operation.

A transaction must either commit all required records or roll all of them back. Do not implement this as permanent dual writes or best-effort compensating writes.

## Current test coverage and gaps

Existing focused tests cover:

- Audit persistence across reopen, invalid input rejection, tamper detection, and clear/reset behavior.
- Idempotency first claim, duplicate suppression, conflicting evidence, event-type separation, store recreation, and required identifiers.
- Action-plan persistence across recreation, batch rollback, update ordering, corrupt payload failure, and legacy missing-`created_at` decoding.
- GitOps lifecycle transitions, approval boundary, dry-run behavior, and in-memory registry behavior.

The existing focused tests do **not** establish MySQL correctness, cross-process audit-chain serialization, multi-worker GitOps cache coherence, atomic lifecycle-plus-audit writes, or idempotency races across independent database connections. Those require integration tests against the selected MySQL-compatible service in CI.

## Cutover gates

Do not change production defaults or remove SQLite paths until all of the following are confirmed:

- The deployment owner confirms the actual MySQL 8.0+ service, TLS/network requirements, credentials delivery, and operational owner.
- A versioned schema migration and repeatable clean-install/upgrade path exist.
- A real database service is used in CI for concurrency and transaction integration tests.
- A read-only preflight captures source schema, counts, tenant distribution, lifecycle states, pending/emitted claims, and a valid full audit-chain export.
- Import comparison, backup restore, point-in-time recovery, rollback, and final write-pause cutover procedures have been exercised in an isolated environment.
- The release retains dry-run-only infrastructure execution.

Until then, the four SQLite stores remain the current runtime behavior and no production data is modified by this inventory.
