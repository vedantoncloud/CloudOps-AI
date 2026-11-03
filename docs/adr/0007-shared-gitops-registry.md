# ADR 0007: Shared SQL GitOps registry and cross-worker coherence

- Status: Implemented adapter; production enablement remains opt-in and gated.
- Date: 2026-11-03
- Related: ADR 0001 through ADR 0006

## Decision

The GitOps change-set registry now supports the shared Alembic schema through an explicit SQLAlchemy `database_url`. The API selects `CLOUDOPS_DATABASE_URL` when configured; otherwise the existing SQLite registry remains the default.

Migration 0004 adds a singleton `gitops_state` allocator seeded from the current maximum `created_order`. New registrations lock that row and insert the change set, relational tenant ID, payload, and order in one transaction. Reads (`get`, `list_all`, `list_pending`, and `require`) refresh from the shared database rather than trusting the process-local cache.

Transitions lock the current row and compare the persisted payload with the exact prior snapshot before updating. A stale worker cannot overwrite a newer approval, rejection, apply, or verification state; it receives a conflict and refreshes its local cache. Tenant-scoped transitions also re-check the authenticated tenant inside the registry boundary, rather than relying only on an earlier API visibility read. The same registry lock serializes operations within a process. SQLite shared-URL tests use `BEGIN IMMEDIATE`; MySQL uses row locks.

## Safety and remaining cutover gate

- No production URL or credentials are configured.
- SQLite remains the default when `CLOUDOPS_DATABASE_URL` is absent.
- Shared GitOps persistence requires Alembic migrations through head.
- Tenant ID is persisted in both the payload metadata and relational column.
- Audit events are still appended after the GitOps state transaction, not in the same database transaction. The cross-store atomicity gap documented in ADR 0002 remains a production cutover gate.
- The GitOps apply engine's existing dry-run safety boundary is unchanged; real infrastructure mutations remain disabled.
- No existing SQLite data is copied or deleted.

## Validation

- SQLite/SQLAlchemy tests cover cross-registry refresh, stale transition rejection, concurrent order allocation, remote clear, and migration gating.
- MySQL 8.4 tests cover cross-worker state visibility, stale-worker fencing, and concurrent registration order allocation.
- Existing SQLite GitOps lifecycle and API tests remain part of the full backend suite.
