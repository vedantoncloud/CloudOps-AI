# Shared persistence migration and cutover runbook

**Status: preparation only. This runbook is not approval to perform a production cutover.**

The application has opt-in shared SQL adapters for audit events, audit idempotency, action plans, and GitOps state. The default Docker configuration still points to four SQLite files. A deterministic, dry-run-first importer is now implemented, but no production database endpoint or credentials have been supplied and no production import or cutover has been approved. Setting `CLOUDOPS_DATABASE_URL` against an empty database before importing the legacy records would hide existing operational state. Do not switch production to shared SQL without the owner approvals and staged procedure below.

## 1. Required owner confirmations

Before provisioning or connecting a production target, the deployment owner must confirm:

- The target is MySQL 8.0+ compatible (CI currently validates MySQL 8.4).
- Managed database service, network path, TLS requirements, connection limits, and operational owner.
- Secret delivery and rotation mechanism; credentials must never be committed or included in logs.
- Backup retention, point-in-time recovery (PITR), restore owner, and a tested recovery objective.
- Maintenance window, write-freeze owner, rollback criteria, and tenant/data validation approver.

If the actual target is PostgreSQL or another dialect, revisit ADR 0001 before proceeding.

## 2. Validate the four SQLite sources

Run this on the existing source environment before setting `CLOUDOPS_DATABASE_URL`:

```bash
cd backend
python persistence_preflight.py
```

Expected result: JSON `status` is `ready`, with `status: ok` for all four stores. Exit code `0` means all source checks passed. Exit code `1` means a source is missing or invalid. Exit code `2` means shared-database mode is already configured; this preflight is intended for the SQLite source phase only.

The command checks SQLite integrity, schemas, audit hash-chain integrity, idempotency claim/evidence consistency, and application-level readability using isolated temporary copies. It does not modify the source files.

## 3. Take and verify source backups

Using an admin token, download each legacy SQLite snapshot:

| Store | Admin endpoint |
|---|---|
| Audit events | `/autonomy/audit/database/backup` |
| Audit idempotency | `/autonomy/audit/database/backup/idempotency` |
| Action plans | `/autonomy/audit/database/backup/action-plans` |
| GitOps changes | `/autonomy/audit/database/backup/gitops` |

Verify every downloaded file before moving it to protected migration storage:

```bash
python verify_database_backup.py audit <audit-backup.db>
python verify_database_backup.py idempotency <idempotency-backup.db>
python verify_database_backup.py action-plans <action-plans-backup.db>
python verify_database_backup.py gitops <gitops-backup.db>
```

Expected result: each command exits `0` and reports `status: ok`. Keep snapshots encrypted, access-controlled, and read-only. Never place them in the repository.

## 4. Provision and migrate an isolated target

After the owner confirms the target and secret delivery, provision an isolated staging database with the production-equivalent MySQL version, TLS, network rules, and backup configuration. Inject `CLOUDOPS_DATABASE_URL` through the deployment secret mechanism; do not write it to source control.

Apply the versioned schema from the backend directory:

```bash
cd backend
alembic upgrade head
```

The application stores validate the required tables and do not create the shared schema automatically. The `/ready` endpoint checks database reachability, Alembic revision metadata, required tables, and singleton state rows.

Run the full MySQL integration suite and exercise audit integrity, audit health/reconciliation, action-plan lifecycle, GitOps transitions, and multi-worker idempotency before considering the target technically ready.

## 5. Data import is a hard gate

The importer is implemented in `backend/import_legacy_persistence.py`. It requires all four source snapshots, a target already migrated through Alembic head, and an explicitly configured `CLOUDOPS_DATABASE_URL`. The default mode is a read-only dry run; no target data is written unless `--apply` is supplied.

Run the dry run from the backend directory, using the protected backup paths:

```bash
python import_legacy_persistence.py \
  --audit-events /secure/audit-events.db \
  --audit-idempotency /secure/audit-idempotency.db \
  --action-plans /secure/action-plans.db \
  --gitops /secure/gitops.db
```

Review the deterministic `manifest_sha256`, counts, audit final hash, and ordering high-water marks. The importer validates the full audit chain, idempotency states/evidence/tokens, payload identifiers, tenant values, source schemas, and target emptiness. It preserves:

- Every audit event's exact JSON, sequence, and SHA-256 hash.
- Every idempotency key, evidence payload, status, lease timestamp, and claim token.
- Action-plan IDs, tenant ownership, payloads, and creation order.
- GitOps change IDs, tenant ownership, payloads, and creation order.

After the dry-run report has been reviewed and the database/application owners have approved the operation, run the exact same command with `--apply`. The four stores, three allocator heads, and import-ledger marker are written in one SQL transaction. An exact retry returns `already_imported`; a different manifest or non-empty target is rejected. Source SQLite files are opened read-only, and the audit-chain validation uses an isolated temporary snapshot.

This importer is a migration primitive, not an approval to import production data. Keep the target isolated from application writers until the import and independent reconciliation are complete.

Run the independent, read-only source-to-target reconciliation after import and before any application writer is connected. Use the same frozen snapshots and target URL:

```bash
python verify_persistence_import.py \
  --audit-events /secure/audit-events.db \
  --audit-idempotency /secure/audit-idempotency.db \
  --action-plans /secure/action-plans.db \
  --gitops /secure/gitops.db
```

Expected result: exit code `0`, JSON `status: ok`, and an empty `mismatches` list. The verifier independently compares every source record with its target counterpart, recomputes both source and target audit hash chains (`target_audit_chain_valid` must be `true`), checks GitOps tenant attribution, all three allocator heads, the import manifest/ledger, and pending/emitted idempotency counts. It performs no writes. Any `mismatch` or `not_ready` result is a hard stop: keep the target isolated, investigate, and do not proceed to deployment or cutover.

## 6. Future cutover sequence (only after importer approval)

1. Announce maintenance and pause all writers on the source deployment.
2. Take final consistent SQLite snapshots and run all four restore drills.
3. Obtain explicit approval from the database owner and application owner to run the importer against the isolated target.
4. Run importer dry-run; review the manifest and compare source/target counts, keys, tenant attribution, lifecycle states, pending/emitted claims, and complete audit-chain integrity.
5. Obtain final approval, then run the same importer command with `--apply` against the frozen snapshots and repeat all independent reconciliation checks.
6. Set `CLOUDOPS_DATABASE_URL` in the deployment secret store and deploy the shared-SQL application.
7. Confirm `/ready`, `/autonomy/audit/integrity`, `/autonomy/audit/health`, and `/autonomy/audit/reconciliation` are healthy; exercise two-worker lifecycle and idempotency checks.
8. Keep source snapshots immutable for the agreed rollback and retention period. Do not dual-write to SQLite and MySQL.

## 7. Rollback and recovery

Before any shared-database writes, revert the deployment configuration to the untouched SQLite source and investigate the target failure. After shared-database writes have started, reverting to old SQLite files would discard new state. Do not do that without an approved reverse-import or recovery procedure. Use managed MySQL PITR/snapshots and the database owner's restore process for shared-SQL recovery.

The shared database backup endpoints intentionally return a provider-managed backup message instead of attempting to download a MySQL file as SQLite. Real AWS infrastructure mutations remain disabled; this persistence work does not change execution safety settings.
