# Shared persistence migration and cutover runbook

**Status: preparation only. This runbook is not approval to perform a production cutover.**

The application has opt-in shared SQL adapters for audit events, audit idempotency, action plans, and GitOps state. The default Docker configuration still points to four SQLite files. No production database endpoint or credentials have been supplied, and no data importer has been implemented or approved. Setting `CLOUDOPS_DATABASE_URL` against an empty database would make the application use empty shared tables instead of the existing SQLite records. Do not switch production to shared SQL until the data-import phase below is implemented, reviewed, and tested.

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

**Do not cut over yet.** The repository currently has schema migrations, shared-store adapters, SQLite source preflight, and backup verification, but it does not yet have an approved, resumable importer that transfers all four source stores into MySQL.

The importer must be designed and reviewed separately. It must preserve:

- Every audit event's exact canonical JSON, sequence, and SHA-256 hash-chain order.
- Every idempotency key, evidence payload, status, lease timestamp, and claim token.
- Action-plan IDs, tenant ownership, payloads, and creation order.
- GitOps change IDs, tenant ownership, payloads, and creation order.

It must be deterministic, resumable, transactionally safe, and able to produce source/target reconciliation evidence. A dry-run import plan and count/hash comparison must pass before any write to the target.

## 6. Future cutover sequence (only after importer approval)

1. Announce maintenance and pause all writers on the source deployment.
2. Take final consistent SQLite snapshots and run all four restore drills.
3. Run importer dry-run; compare source and target counts, keys, tenant attribution, lifecycle states, pending/emitted claims, and complete audit-chain integrity.
4. Obtain explicit approval from the database owner and application owner.
5. Run the approved import into the isolated target, then repeat all reconciliation checks.
6. Set `CLOUDOPS_DATABASE_URL` in the deployment secret store and deploy the shared-SQL application.
7. Confirm `/ready`, `/autonomy/audit/integrity`, `/autonomy/audit/health`, and `/autonomy/audit/reconciliation` are healthy; exercise two-worker lifecycle and idempotency checks.
8. Keep source snapshots immutable for the agreed rollback and retention period. Do not dual-write to SQLite and MySQL.

## 7. Rollback and recovery

Before any shared-database writes, revert the deployment configuration to the untouched SQLite source and investigate the target failure. After shared-database writes have started, reverting to old SQLite files would discard new state. Do not do that without an approved reverse-import or recovery procedure. Use managed MySQL PITR/snapshots and the database owner's restore process for shared-SQL recovery.

The shared database backup endpoints intentionally return a provider-managed backup message instead of attempting to download a MySQL file as SQLite. Real AWS infrastructure mutations remain disabled; this persistence work does not change execution safety settings.
