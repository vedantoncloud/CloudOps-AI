# Shared database deployment and recovery

This runbook describes the existing shared SQL persistence path. It does not
provision a database, create credentials, deploy CloudOps AI, or enable live
infrastructure mutations.

## What uses the shared database

When `CLOUDOPS_DATABASE_URL` is configured, the application uses that URL for
these durable stores:

- Audit events and the audit-chain head.
- Audit idempotency claims.
- Action plans and their creation-order state.
- GitOps change sets and their creation-order state.
- Shared fixed-window request-rate counters.

Use the **same URL and schema** for every API replica. The supported URL forms
are `mysql+pymysql://...` and `sqlite:///...`. A SQLite URL coordinates
processes sharing one local file; it is not a network database for separate
hosts. Use MySQL for hosts that need a common network database.

The legacy SQLite environment variables remain relevant only when the shared
URL is not configured:

| Store | Legacy path setting |
| --- | --- |
| Audit events | `CLOUDOPS_AUDIT_EVENTS_DB` |
| Audit idempotency | `CLOUDOPS_AUDIT_IDEMPOTENCY_DB` |
| Action plans | `CLOUDOPS_ACTION_PLANS_DB_PATH` |
| GitOps change sets | `CLOUDOPS_GITOPS_DB_PATH` |

## Prerequisites and safety

- Use a supported MySQL deployment (the CI migration job currently exercises
  MySQL 8.4) and the pinned backend dependencies, including PyMySQL.
- Create a dedicated database and least-privilege application/migration
  credentials. The migration identity needs DDL rights; the runtime identity
  needs the DML rights required by the application. Keep credentials in a
  secret manager or protected runtime environment, never in Git.
- URL-encode reserved characters in database usernames/passwords.
- Ensure the database is reachable from the migration runner and every API
  replica. Keep host clocks synchronized.
- Schedule a maintenance window. Stop all CloudOps API replicas and any other
  writers before taking the four legacy-store preflight/import snapshots.
  The four independent SQLite files do not form one cross-file transaction;
  stopping writers prevents a mixed-time migration.
- Take protected backups of all four SQLite files before proceeding. Do not
  delete or overwrite the source files during migration.

## 1. Configure the target and apply migrations

Set `CLOUDOPS_DATABASE_URL` in the migration environment. Do not put a real
password in a command copied into shell history. The URL format is:

```sh
mysql+pymysql://DB_USER:DB_PASSWORD@DB_HOST:3306/DB_NAME?charset=utf8mb4
```

From the repository root, run the migrations with the same URL that will be
used by the application:

```sh
alembic -c backend/alembic.ini upgrade head
```

The migration environment refuses to run unless `CLOUDOPS_DATABASE_URL` is
explicitly set. `upgrade head` applies the complete migration chain (currently
revisions 0001 through 0007), including the shared rate-limit counter table.
Use a fresh, dedicated target database for the legacy import. Do not point this
procedure at a database that already contains application records.

## 2. Run the read-only legacy preflight

With the application still stopped and **without** setting
`CLOUDOPS_DATABASE_URL`, run this from `backend/`:

```sh
python persistence_preflight.py
```

The script checks the four configured legacy SQLite files (or their defaults
under `/var/lib/cloudops`). It opens sources read-only, validates SQLite
integrity and application-level records, and emits sanitized counts. A
successful report has top-level `"status": "ready"` and each store has
`"status": "ok"`. Missing or invalid stores make the preflight fail.

If the files are stored elsewhere, set the corresponding four legacy path
environment variables listed above before running the script. Preserve the
report with the migration change record; it contains counts, not database
contents. The script deliberately refuses to run if
`CLOUDOPS_DATABASE_URL` is set.

## 3. Dry-run, review, then import

Set `CLOUDOPS_DATABASE_URL` to the migrated, empty target database. From
`backend/`, run the importer with the exact four source paths. First omit
`--apply`:

```sh
python import_legacy_persistence.py \
  --audit-events /secure/source/audit-events.db \
  --audit-idempotency /secure/source/audit-idempotency.db \
  --action-plans /secure/source/action-plans.db \
  --gitops /secure/source/gitops.db
```

Review the JSON dry-run report and retain its manifest SHA-256 and per-store
counts. The importer validates source integrity, audit-chain continuity,
idempotency claims, payload identities, tenant field limits, and creation
orders. It refuses duplicate source paths, an incomplete target schema, or a
target whose persistence tables are not empty.

Only after reviewing the report, run the same command with `--apply` appended.
The importer writes all four stores, their state heads, and an import-ledger
record in one target transaction. It is dry-run-first and manifest-fenced:
repeating the exact manifest is reported as `already_imported`; a different
manifest is not silently layered over an existing import.

Do not start application replicas during the import. If the import fails,
inspect the sanitized error, preserve the source files and target for
investigation, and do not manually edit the import ledger or persistence
tables.

## 4. Start and verify the application

Configure the identical `CLOUDOPS_DATABASE_URL` on every API replica along
with the normal production authentication, tenant-role, and AWS environment
settings. Start one replica first and check:

- `GET /health` confirms process liveness only.
- `GET /ready` checks the configured persistence schema and other required
  dependencies; it must report ready before routing traffic.
- Confirm expected audit, action-plan, and GitOps records through their
  authenticated application interfaces.
- Confirm the same database URL is configured on every replica.

The application checks required shared tables at readiness. If the shared
database or required schema is unavailable, readiness fails; shared rate
limiting returns HTTP 503 rather than silently falling back to per-process
counters. Do not treat a successful migration command alone as proof that
application data was imported correctly.

## Backups and recovery

### MySQL shared database

The existing admin backup endpoints and `backend/verify_database_backup.py`
are **SQLite-specific**. They are not a MySQL backup or restore mechanism.
For MySQL, use the database provider's supported automated backup/PITR
capability or a tested MySQL-native logical/physical backup process. Protect
backup encryption keys and credentials separately from the database host.

Before a release or schema migration, take a recoverable database backup and
record its timestamp, database identity, migration revision, and retention
expiry. Periodically restore a backup into an isolated, non-production
database, apply any required forward migrations there, and verify the
application can reach it and pass readiness. A backup is not considered
operationally tested until an isolated restore has succeeded.

For an incident, stop all API replicas and writers, preserve the affected
database and logs, and restore the chosen backup/PITR point using the database
provider's documented procedure. Reconcile the restored migration revision
with the deployed application version before starting the service. Start one
replica, verify readiness and representative records, then re-enable traffic.
If writes occurred after the selected recovery point, account for that data
loss explicitly; do not claim that restoring a backup reconstructs those
writes.

### Legacy SQLite stores

When using the default SQLite deployment (shared URL unset), the admin backup
endpoints documented in the README can snapshot the audit, action-plan, and
GitOps stores individually. The idempotency store also needs a protected
backup; do not assume the three API backup endpoints cover all four stores.
The SQLite restore-drill script supports the store names `audit`,
`idempotency`, `action-plans`, and `gitops`:

```sh
python backend/verify_database_backup.py audit /secure/backup/audit.db
python backend/verify_database_backup.py idempotency /secure/backup/idempotency.db
python backend/verify_database_backup.py action-plans /secure/backup/action-plans.db
python backend/verify_database_backup.py gitops /secure/backup/gitops.db
```

Run these checks against copies, not the live database files. They validate
SQLite integrity and application-level readability; they do not replace a
full restore rehearsal.

## Rollback boundaries

- Before import, the legacy SQLite files remain the source of truth. If
  preflight or dry-run fails, stop and investigate without changing sources.
- The importer uses one target transaction. A failed transaction should not
  leave a partial four-store import; verify the target before retrying.
- After the application has accepted writes on the shared database, simply
  switching `CLOUDOPS_DATABASE_URL` back to legacy SQLite can discard newer
  writes and split state. Treat that as a data migration, not a configuration
  toggle. Use a planned reverse migration/export procedure or restore from a
  verified backup; do not improvise a rollback during an incident.

## Related documentation

- [Shared distributed request rate limiting](distributed-rate-limiting.md)
- [Deployment, audit export, and SQLite backup details](../README.md)
