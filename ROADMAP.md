# CloudOps AI Roadmap

**Audit snapshot:** 2026-10-14, current working changes after `2e48f93` (`main`). This roadmap has **10 remaining tasks**. The count is the number of numbered, incomplete deliverables below; subtasks and acceptance criteria are not counted separately. Reassess the count when a whole numbered task is complete or the scope is deliberately changed.

## Current state

CloudOps AI is an actively developed FastAPI backend, not yet a production-ready cloud operations product. The repository contains AWS EC2/S3 inventory, health and insight endpoints; planning, policy, approval, simulation, governance and recovery components; provider discovery; and in-memory and SQLite-backed audit capabilities. The latest history adds persistent tamper-evident audit events and persists autonomous run audit events. The test suite is extensive (303 `test_*.py` modules), including API contracts, governance isolation, malformed input, concurrency, and audit integrity cases. Focused access-control and assembled API tests pass; the full suite has not been run for this change.

The README still labels React, PostgreSQL, Docker, GitHub Actions, Terraform, Kubernetes, and AI/LLM integration as planned stack items. No corresponding frontend, deployment/CI/IaC manifests, or LLM integration were found in the repository. `ActionExecutor` explicitly supports dry-run only and rejects real infrastructure execution. The current durable audit implementation is SQLite, so persistence across process restarts is implemented, but it is not a shared production database service. A first bearer-token boundary now supports configured roles and tenant claims at the assembled API; autonomous-run lifecycle and verification events persist principal attribution. Provider-neutral resource inventory and governance reads now enforce a `CloudOpsTenantId` ownership tag in token mode, while direct AWS inventory/insight routes, AWS account isolation, and attribution for other API operations remain outstanding.

## Completed capabilities

- FastAPI service foundation and AWS connectivity/service-health checks.
- EC2 and S3 inventory, filtering, metrics, security, cost-awareness, and optimization insights.
- Autonomous action models/planning, policy evaluation, approval gates, dry-run execution, verification, recovery, and rollback foundations.
- Governance and provider abstractions, resource discovery, blast-radius/dependency planning, simulation, and cost/security decision support.
- Audit event filtering, pagination/export, actor/resource/time filters, hash-chain integrity checks, diagnostics, and API coverage.
- Persistent audit event storage and autonomous-run event persistence, with extensive SQLite validation, idempotency, reconciliation, and concurrency tests.

## Prioritized remaining work

1. **Establish API access control and tenant boundaries (P0).** In progress: the assembled API supports bearer tokens configured by `CLOUDOPS_API_TOKENS`, reader/operator/admin method-based authorization, request principal and tenant context, and mismatched `X-Cloud-Tenant` rejection. Audit diagnostics require admin; approval POSTs remain operator-level. Autonomous-run lifecycle and verification events persist the authenticated request principal as `actor_id`. Provider-neutral resource inventory and governance reads, plus direct EC2 inventory and summary, enforce the `CloudOpsTenantId` resource tag in token mode; missing and cross-tenant EC2 ownership tags are hidden and summary totals use only visible instances. Remaining: scope the other direct `/cloud/aws/*` data routes and AWS account credentials by tenant, expand tenant tests across privileged operations, use an external identity provider for credential lifecycle, and include the principal in audit events from other API operations. **Done when:** all protected endpoints reject unauthenticated or unauthorized requests, cross-tenant access is prevented and tested across resource APIs, and audit records identify the authenticated principal.

2. **Define a production persistence architecture (P0).** Move operational state and audit/idempotency records from process-local or SQLite-only assumptions to a supported shared database, with schema migrations, transaction/locking semantics, backup/restore, retention, and upgrade procedures. The current SQLite audit stores are durable local files, not evidence of PostgreSQL support. **Done when:** clean install and upgrade migrations work against the chosen database, restart/concurrency behavior is verified, and restore/retention procedures are documented.

3. **Build a safe, narrowly scoped real-action execution path (P0).** Keep dry-run as default; implement only explicitly selected reversible AWS actions with least-privilege permissions, fresh precondition checks, approval binding, idempotency, bounded retries, verification, and tested rollback. **Done when:** each enabled action has an action-specific threat/safety review and integration coverage, and all other mutations remain denied.

4. **Add deployment and environment configuration (P1).** Provide a reproducible container/runtime setup, configuration validation, secret injection guidance, TLS/reverse-proxy expectations, and separate development/staging/production settings. **Done when:** a documented clean deployment starts without source edits and fails safely on missing or invalid required configuration.

5. **Create automated CI quality gates (P1).** Add a supported Python version matrix, dependency installation, test execution, lint/type checks, and dependency/security scanning with actionable failure output. **Done when:** pull requests run the gates and the supported commands/results are documented. (The audit did not run the existing suite.)

6. **Make health and operations observable (P1).** Split liveness from dependency/readiness checks; add structured logs, request correlation, metrics, and actionable AWS/database failure signals without exposing secrets or sensitive audit payloads. **Done when:** operators can distinguish app health from dependency health and diagnose failed requests from documented telemetry.

7. **Harden API and AWS operational limits (P1).** Set request/response size limits, pagination bounds, timeouts, rate limits, AWS retry/backoff and throttling behavior, and consistent error contracts. **Done when:** limits are explicit and tested under malformed, oversized, throttled, and unavailable-dependency conditions.

8. **Specify audit trust, retention, and recovery guarantees (P1).** Document the hash-chain threat model and key/anchor strategy; define tamper detection, export verification, retention, access, backup, and disaster recovery. A hash chain stored in a writable database alone does not prevent an attacker who can rewrite the whole store from recomputing it. **Done when:** an operator can independently verify exported history and follow tested backup/restore and incident procedures.

9. **Close user-facing product scope (P2).** Decide whether the planned React console and AI/LLM integration remain in scope. If yes, deliver a secured UI for inventory, governance, approvals, and run history, and introduce model-assisted functionality only behind explicit policy and human review; otherwise update README to state the supported API-only scope. **Done when:** the product scope and corresponding deliverable are implemented and documented; no AI-driven mutation bypasses the approval/safety controls.

10. **Publish operating and support documentation (P2).** Replace the short project-status README with setup, configuration, API/auth model, AWS IAM permissions, data flows, architecture, limitations, incident response, upgrade, and support guidance. **Done when:** a new operator can deploy, validate, recover, and safely disable the service using repository documentation alone.

## Technical debt and readiness gaps

- Several autonomy subsystems and API routers are composed in one backend without repository-level architecture or deployment documentation.
- Current audit persistence uses local SQLite files; the untracked SQLite files in this checkout were preserved and not inspected or changed.
- Real AWS mutations are intentionally disabled. Insight and planning coverage must not be presented as completed autonomous remediation.
- The health endpoint reports a static application status and does not establish that AWS or persistence dependencies are ready.
- No CI workflow, container/deployment configuration, infrastructure-as-code, or frontend was found in the inspected repository. API authentication has a configurable bearer-token boundary; autonomous-run events have principal attribution. The provider-neutral resource API uses ownership tags for tenant isolation, while direct AWS endpoints/account isolation, external credential lifecycle, and attribution for other API events remain outstanding.
- Requirements are pinned, but no automated dependency update/security workflow or documented supported Python runtime was found.
- Cost insights explicitly describe themselves as qualitative; actual billing/pricing integration remains outside current behavior.

## Scope and counting rule

This is a finite delivery backlog of 10 outcomes, not an assertion that every possible feature is included. Items 1–8 address minimum security, execution safety, and operating readiness; items 9–10 settle and document product scope. New scope should be added as a numbered task only after explicitly replacing or extending this backlog.
