# CloudOps AI Roadmap

**Repository audit:** 2026-10-16, updated after adding bounded S3 bucket analysis to the secured operations console. This roadmap contains **9 remaining tasks**: the nine numbered incomplete outcomes below. Sub-bullets and acceptance criteria do not count separately. Recount only when a complete outcome ships or scope is explicitly changed.

## Current state

CloudOps AI is a FastAPI backend with AWS EC2/S3 inventory and insight routes, planning and governance systems, approval workflows, dry-run execution, recovery, provider abstractions, and audit capabilities. The history shows sustained feature and hardening work, especially around persistent audit idempotency/reconciliation, governance contracts, and audit integrity. There are **305 `test_*.py` modules** under `backend/tests`; this is a file count, not a test-case count or a claim that they pass. The test suite was not run during this repository audit.

Recent commits added configurable bearer-token access control, admin-only audit diagnostics, autonomous-run audit attribution, provider-neutral resource tenant filtering, and tenant filtering for EC2 inventory/summary/detail and aggregate insights. In token mode, the `CloudOpsTenantId` tag scopes provider-neutral `/autonomy/resources` inventory/governance, EC2 inventory/summary/detail/aggregate insights, and direct S3 bucket inventory/detail/object/insight routes. S3 bucket access fails closed when its ownership tag cannot be read; deployments need `s3:GetBucketTagging` for those checks. The AWS client/account context is also shared rather than selected by tenant. Development remains the default environment and authentication mode, but `CLOUDOPS_ENV=production` now requires token mode and a nonempty token registry at startup. Tokens and claim validation exist; token issuance, rotation, revocation, and federation remain upstream responsibilities. Autonomous-run events include the authenticated subject; attribution is not consistently wired through other operations.

The audit trail and idempotency/reconciliation state persist to SQLite files and have substantial validation and concurrency coverage. This is not a shared production database architecture. `ActionExecutor` rejects real infrastructure execution; execution remains dry-run only. Autonomous lifecycle audit events now back an authenticated, actor-scoped, paginated `/autonomy/runs` history endpoint. `/console` serves a lightweight authenticated browser console for inventory, governance, approvals, and run history. The repository has a README and roadmap, but `docs/` is empty. No Docker/container setup, CI workflow, Terraform/Kubernetes configuration, migration framework, or LLM integration was found. Requirements are pinned, but no supported Python version is documented. Cost insights describe qualitative estimates, not live billing data.

## Completed work

- FastAPI application and AWS service status/connectivity checks.
- EC2 and S3 inventory, filtering, metrics, security, cost-awareness, and optimization insights.
- Autonomous action models and planning; policy/governance decisions; approval gates; simulation; dry-run execution; verification, recovery, and rollback foundations.
- Provider/resource discovery abstractions, blast-radius and dependency planning, control-loop/control-plane APIs, and GitOps proposal/registry flows.
- In-memory audit filtering, pagination/export, actor/resource/time filters, hash-chain integrity verification, and diagnostics.
- SQLite-backed persistent audit events and autonomous-run audit events, plus idempotency, reconciliation, health checks, and extensive malformed-input/concurrency tests.
- Configurable development/token access modes, method-based reader/operator/admin authorization, tenant claim/header checks, admin-only audit diagnostics, autonomous-run actor attribution, and partial resource/EC2/S3 tenant filtering.
- Production environment startup validation rejects permissive development authentication and requires configured bearer tokens.
- Aggregate EC2 efficiency, cost, rightsizing, and security insights analyze only authenticated-tenant inventory in token mode.
- Authenticated users can retrieve an individual EC2 inventory record through `GET /cloud/aws/ec2/instances/{instance_id}`; token-mode results use the tenant-filtered inventory and hide foreign, untagged, and missing IDs uniformly.
- Authenticated operators can list their durable autonomous run history through `/autonomy/runs`, with lifecycle summaries and bounded pagination.
- Authenticated users can browse the in-memory action-plan queue through `/autonomy/plans`, filter by lifecycle status, and page through results; token-mode plan access is restricted to the tenant that created each plan.
- Non-admin authenticated users can list and export only their own audit events; admins retain cross-actor audit access.
- Operators can browse a tenant-scoped, newest-first pending approval queue through `/autonomy/approvals`, with bounded pagination.
- Operators can reject a pending action plan with a required reason; the response records the authenticated reviewer and exposes a distinct `rejected` status.
- Operators can cancel a pending action plan with the authenticated actor recorded as its decision maker, matching approval and rejection attribution in plan state.
- Authenticated users can retrieve an action plan's current state through `GET /autonomy/plans/{action_id}`; token-mode lookups hide plans belonging to another tenant.
- Operators can distinguish process liveness (`/health`) from dependency readiness (`/ready`); readiness checks AWS and both persistent SQLite stores, returns 503 when any dependency is unavailable, and does not expose account or error details.
- Authenticated users can resume S3 object listings from an AWS continuation token through `/cloud/aws/s3/buckets/{bucket_name}/objects`; responses expose truncation state and the next token for incremental browsing.
- Authenticated users can use `/console` to browse EC2/S3 inventory, inspect resource governance, review and decide pending approvals, and view their autonomous run history; bearer credentials stay in page memory.
- Token-scoped EC2/S3 plan generation verifies the source resource's tenant ownership first; foreign, untagged, missing, or unverifiable resources are hidden before insight analysis.
- The operations console can create action plans from EC2/S3 resource insights, browse and filter the plan queue, evaluate plans, cancel eligible plans, and run approved plans in dry-run mode.
- The operations console can browse S3 bucket objects by prefix, choose a bounded page size, and continue through truncated listings.
- The operations console can analyze an S3 bucket by optional prefix, showing object statistics, storage health, security findings, cost opportunities, and largest objects from bounded scans of up to 1,000 objects; each analysis result reports failures independently.
- The operations console can page through action plans in batches of 50, append older plans, and reset pagination when the status filter or refresh changes.
- Operators can inspect a plan from the console queue and retrieve its current tenant-scoped state, including the full plan details.
- The operations console can load EC2 fleet efficiency, cost, rightsizing, and security insights from the aggregate APIs; token-mode analysis is limited to authenticated-tenant instances.
- Authenticated users can browse audit history in the operations console, filter events by resource ID, and load additional bounded pages through the actor-scoped audit API.
- The operations console can open EC2 inventory and metrics or S3 bucket details and insights from each resource row, with independent error reporting when one detail request fails.
- EC2 and S3 action-plan generation uses `POST` because it creates plan records; token-mode readers are denied and operators can create tenant-scoped plans.

## Prioritized remaining work

1. **Complete API authorization, tenant isolation, and attribution (P0).** Extend resource ownership enforcement to every tenant-sensitive direct AWS inventory, detail, metric, and insight route; establish tenant-specific AWS account/credential boundaries; verify access rules across privileged operations; consistently attach the authenticated principal to audit events. Define and operate token issuance, rotation, revocation, and external identity integration. **Done when:** every protected route has an explicit tested authorization policy, cross-tenant reads are prevented across all AWS/resource routes and account boundaries, and operational audit events identify their actor.

2. **Adopt a production persistence architecture (P0).** Select a supported shared database for operational state and audit/idempotency records. Provide schema migrations, transaction and locking behavior, backup/restore, retention, and upgrade procedures. Existing SQLite persistence is local-file durability, not shared database support. **Done when:** clean installation and upgrades work against the chosen database, restart/concurrency behavior is verified, and restore/retention procedures are documented and exercised.

3. **Keep infrastructure execution safely disabled until a scoped action is ready (P0).** Real mutations are currently rejected. If enabling execution, start with explicitly selected reversible AWS actions and implement least-privilege permissions, fresh precondition checks, approval binding, idempotency, bounded retries, verification, and tested rollback. **Done when:** every enabled mutation has an action-specific safety review and integration coverage; all unimplemented mutations remain denied. If no real-action scope is approved, document dry-run-only operation as the supported release behavior.

4. **Provide deployment and environment configuration (P1).** Production startup validation now requires token auth and configured credentials. Remaining work: add a reproducible runtime/container setup, broader configuration validation, secret injection guidance, TLS/reverse-proxy expectations, and documented development/staging/production settings. **Done when:** a documented clean deployment starts without source edits and rejects unsafe or missing production configuration.

5. **Add automated CI quality gates (P1).** Define supported Python versions and add dependency installation, test execution, lint/type checks, and dependency/security scanning with actionable failure output. **Done when:** pull requests run the documented gates and report failures reliably.

6. **Make health and operations observable (P1).** `/health` now provides liveness and `/ready` reports AWS dependency readiness with sanitized responses. Add structured logs, request correlation, metrics, database readiness, and actionable AWS/database failure signals without exposing secrets or sensitive audit payloads. **Done when:** operators can distinguish application health from dependency health and diagnose failures using documented telemetry.

7. **Harden API and AWS operational limits (P1).** Set request/response size limits, pagination bounds, timeouts, rate limits, AWS retry/backoff and throttling behavior, and consistent error contracts. **Done when:** limits are explicit and covered for malformed, oversized, throttled, and unavailable-dependency conditions.

8. **Specify audit trust, retention, and recovery guarantees (P1).** Document the hash-chain threat model and external key/anchor strategy; define tamper detection, export verification, retention, access, backup, and disaster recovery. A hash chain stored in a writable database cannot by itself prevent an attacker with full store access from rewriting the history and recomputing the chain. **Done when:** an operator can independently verify exported history and follow tested backup/restore and incident procedures.



9. **Publish operating and support documentation (P2).** Expand the short README with setup, configuration, API/auth model, AWS IAM permissions, data flows, architecture, limitations, incident response, upgrade, and support guidance. **Done when:** a new operator can deploy, validate, recover, and safely disable the service using repository documentation alone.

## Technical debt and production-readiness gaps

- Authentication defaults to permissive development mode unless `CLOUDOPS_ENV=production` is set; production then requires token mode and configured tokens. The token boundary does not itself provide credential lifecycle management.
- Tenant isolation is partial: provider-neutral resources, EC2 list/summary/detail and aggregate insights, and direct S3 bucket routes are filtered by ownership tags, while AWS account credentials are not tenant-scoped. S3 checks require bucket-tag read permission and hide resources when ownership cannot be established.
- Audit actor attribution is implemented for autonomous runs and approval/rejection/cancellation plan state, but not consistently for all API operations. Audit event listing/export is actor-scoped for non-admin users; the underlying shared trail and operational diagnostics still require broader tenant and attribution work.
- Persistent audit stores are SQLite local files; there is no shared production database, migration, backup, or restore workflow.
- Real infrastructure mutations are intentionally disabled; planning, governance, and simulation must not be represented as completed remediation.
- `/health` remains a static liveness check; `/ready` checks AWS and configured persistence stores but does not yet provide structured logs, request correlation, metrics, or actionable diagnostic signals.
- No CI workflow, deployment/container configuration, IaC, or substantive operator documentation was found; `docs/` is empty. The console is a lightweight browser client served by FastAPI, with inventory/governance, plan generation, inspection and review, approvals, and run history.
- No supported Python runtime or automated dependency update/security workflow is documented.
- Cost insights are qualitative; live billing/pricing integration is not present.
- The checkout contains untracked SQLite database files. They were left untouched and are not part of this roadmap change.

## Scope and count

This is a finite backlog of nine remaining delivery outcomes, not a claim to enumerate every possible product feature. Items 1–8 cover security, safe execution, and operational readiness; item 9 covers operating documentation. Add numbered work only when deliberately replacing or extending this scope.
