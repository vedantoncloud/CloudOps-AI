# ADR 0013: Deterministic legacy persistence importer

- Status: Implemented; production use remains approval-gated
- Date: 2026-11-03
- Related: ADR 0001, ADR 0003, ADR 0011, ADR 0012

## Context

The shared SQL schema and four shared-store adapters are in place, but switching `CLOUDOPS_DATABASE_URL` before importing the existing SQLite records would hide operational history and lifecycle state. The four legacy stores must be copied as one consistent dataset.

## Decision

Add `backend/import_legacy_persistence.py` as a dry-run-first importer. It requires explicit paths for all four source SQLite files and an explicit `CLOUDOPS_DATABASE_URL` target. The default mode is read-only and emits a deterministic SHA-256 manifest, source counts, final audit hash, and ordered-store high-water marks. `--apply` is required to write.

Before writing, the importer validates SQLite integrity and required columns, verifies the full audit hash chain, checks idempotency evidence and claim states, and checks action-plan/GitOps primary keys against their JSON payloads. It derives the GitOps tenant column from the existing payload metadata while preserving the original payload string. It preserves audit sequence, event JSON, event hashes, idempotency tokens and lease timestamps, action-plan tenant/payload/order, and GitOps tenant/payload/order.

The target must already be migrated through Alembic head, contain the expected four stores and singleton allocator rows, and have empty persistence tables. Import of all four stores, all three allocator heads, and a manifest ledger row occurs in one SQL transaction. The manifest hash is the retry key: repeating the exact import returns `already_imported`; a different manifest cannot overwrite an already-populated target.

## Operational procedure

1. Freeze all source writers for the final snapshot window.
2. Run `python persistence_preflight.py` and verify all four sources are ready.
3. Take and verify all four source backups using `verify_database_backup.py`.
4. Provision and migrate an isolated target through `alembic upgrade head`.
5. Run the importer without `--apply`; retain and review its manifest report.
6. Obtain explicit application-owner and database-owner approval.
7. Run the same command with `--apply` against the frozen source snapshots.
8. Independently compare source/target counts, tenant ownership, pending/emitted claims, allocator heads, and the full audit hash chain before any deployment setting changes.
9. Only then schedule a separately approved deployment cutover.

## Safety boundaries

The importer does not read credentials from files, print the database URL, configure production secrets, alter source SQLite files, or change runtime routing. It does not enable AWS mutations. It does not perform a production cutover. Source snapshots must remain immutable until the rollback/retention window expires. Once shared-SQL writes begin, stale SQLite files are not a valid rollback target.

## Validation

Tests cover dry-run source immutability, preservation of all four stores and their ordering/tenant/state metadata, target allocator state, import ledger creation, deterministic retry, changed-manifest detection, and refusal to overwrite a non-empty target. MySQL 8.4 integration coverage exercises the migration ledger schema; importer integration tests run against the same SQLAlchemy code path using an isolated migrated SQLite target.
