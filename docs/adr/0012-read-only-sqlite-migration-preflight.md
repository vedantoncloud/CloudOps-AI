# ADR 0012: Read-only SQLite migration preflight

- Status: Implemented
- Date: 2026-11-03
- Related: ADR 0001, ADR 0003, ADR 0011

## Context

The shared persistence adapters and Alembic schema are available, but production cutover still requires a verified inventory of all four legacy SQLite stores. The migration owner needs a repeatable way to check source files before any import or cutover without changing those files.

## Decision

Add `backend/persistence_preflight.py`, a read-only command that inspects the four Docker-configured SQLite sources: audit events, audit idempotency, action plans, and GitOps change sets.

The preflight checks file presence, SQLite integrity, required tables and columns, the full audit hash chain, idempotency claim-state/evidence consistency, and application-level readability of action-plan and GitOps records. Application-level checks use isolated temporary copies created through SQLite's online backup API. The source files are opened read-only and are never modified.

The JSON report contains only store names, statuses, counts, and stable reason codes. It does not expose file paths, tenant identifiers, evidence payloads, or secrets. The command refuses to run when `CLOUDOPS_DATABASE_URL` is already configured, because it is intended to inspect the legacy SQLite source set before cutover.

## Usage

From the repository's `backend` directory:

```bash
python persistence_preflight.py
```

The default paths match the production Docker image. Each path can be overridden with its existing store-specific environment variable. Exit code `0` means all four sources passed; `1` means a source is missing or invalid; `2` means shared-database mode is already configured.

## Validation and safety

- Tests cover all four source stores, a valid audit chain, emitted and pending claim consistency, missing files, and corrupt/unknown states.
- Tests assert source file bytes are unchanged after successful preflight.
- This command performs no import, write, migration, or cutover. Production database credentials and data migration remain separate, explicitly approved operations.
