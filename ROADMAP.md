# CloudOps AI Roadmap

**Repository audit:** 2026-10-14, updated after production authentication startup validation. This roadmap contains **10 remaining tasks**: the ten numbered incomplete outcomes below. Sub-bullets and acceptance criteria do not count separately. Recount only when a complete outcome ships or scope is explicitly changed.

## Current state

CloudOps AI is a FastAPI backend with AWS EC2/S3 inventory and insight routes, planning and governance systems, approval workflows, dry-run execution, recovery, provider abstractions, and audit capabilities. The history shows sustained feature and hardening work, especially around persistent audit idempotency/reconciliation, governance contracts, and audit integrity. There are **305 `test_*.py` modules** under `backend/tests`; this is a file count, not a test-case count or a claim that they pass. The test suite was not run during this repository audit.

Recent commits added configurable bearer-token access control, admin-only audit diagnostics, autonomous-run audit attribution, provider-neutral resource tenant filtering, and tenant filtering for EC2 inventory/summary/detail and aggregate insights. In token mode, the `CloudOpsTenantId` tag scopes provider-neutral `/autonomy/resources` inventory/governance, EC2 inventory/summary/detail/aggregate insights, and direct S3 bucket inventory/detail/object/insight routes. S3 bucket access fails closed when its ownership tag cannot be read; deployments need `s3:GetBucketTagging` for those checks. The AWS client/account context is also shared rather than selected by tenant. Development remains the default environment and authentication mode, but `CLOUDOPS_ENV=production` now requires token mode and a nonempty token registry at startup. Tokens and claim validation exist; token issuance, rotation, revocation, and federation remain upstream responsibilities. Autonomous-run events include the authenticated subject; attribution is not consistently wired through other operations.

The audit trail and idempotency/reconciliation state persist to SQLite files and have substantial validation and concurrency coverage. This is not a shared production database architecture. `ActionExecutor` rejects real infrastructure execution; execution remains dry-run only. The repository has a README and roadmap, but `docs/` is empty. No frontend, Docker/container setup, CI workflow, Terraform/Kubernetes configuration, migration framework, or LLM integration was found. Requirements are pinned, but no supported Python version is documented. Cost insights describe qualitative estimates, not live billing data.

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

## Prioritized remaining work

1. **Complete API authorization, tenant isolation, and attribution (P0).** Extend resource ownership enforcement to every tenant-sensitive direct AWS inventory, detail, metric, and insight route; establish tenant-specific AWS account/credential boundaries; verify access rules across privileged operations; consistently attach the authenticated principal to audit events. Define and operate token issuance, rotation, revocation, and external identity integration. **Done when:** every protected route has an explicit tested authorization policy, cross-tenant reads are prevented across all AWS/resource routes and account boundaries, and operational audit events identify their actor.

2. **Adopt a production persistence architecture (P0).** Select a supported shared database for operational state and audit/idempotency records. Provide schema migrations, transaction and locking behavior, backup/restore, retention, and upgrade procedures. Existing SQLite persistence is local-file durability, not shared database support. **Done when:** clean installation and upgrades work against the chosen database, restart/concurrency behavior is verified, and restore/retention procedures are documented and exercised.

3. **Keep infrastructure execution safely disabled until a scoped action is ready (P0).** Real mutations are currently rejected. If enabling execution, start with explicitly selected reversible AWS actions and implement least-privilege permissions, fresh precondition checks, approval binding, idempotency, bounded retries, verification, and tested rollback. **Done when:** every enabled mutation has an action-specific safety review and integration coverage; all unimplemented mutations remain denied. If no real-action scope is approved, document dry-run-only operation as the supported release behavior.

4. **Provide deployment and environment configuration (P1).** Production startup validation now requires token auth and configured credentials. Remaining work: add a reproducible runtime/container setup, broader configuration validation, secret injection guidance, TLS/reverse-proxy expectations, and documented development/staging/production settings. **Done when:** a documented clean deployment starts without source edits and rejects unsafe or missing production configuration.

5. **Add automated CI quality gates (P1).** Define supported Python versions and add dependency installation, test execution, lint/type checks, and dependency/security scanning with actionable failure output. **Done when:** pull requests run the documented gates and report failures reliably.

6. **Make health and operations observable (P1).** Separate liveness from dependency readiness; add structured logs, request correlation, metrics, and actionable AWS/database failure signals without exposing secrets or sensitive audit payloads. **Done when:** operators can distinguish application health from dependency health and diagnose failures using documented telemetry.

7. **Harden API and AWS operational limits (P1).** Set request/response size limits, pagination bounds, timeouts, rate limits, AWS retry/backoff and throttling behavior, and consistent error contracts. **Done when:** limits are explicit and covered for malformed, oversized, throttled, and unavailable-dependency conditions.

8. **Specify audit trust, retention, and recovery guarantees (P1).** Document the hash-chain threat model and external key/anchor strategy; define tamper detection, export verification, retention, access, backup, and disaster recovery. A hash chain stored in a writable database cannot by itself prevent an attacker with full store access from rewriting the history and recomputing the chain. **Done when:** an operator can independently verify exported history and follow tested backup/restore and incident procedures.

9. **Settle user-facing product scope (P2).** Decide whether the planned React console and AI/LLM integration remain in scope. If retained, deliver a secured UI for inventory, governance, approvals, and run history, and put any model-assisted features behind explicit policy and human review. Otherwise, update the README to state the supported API-only scope and remove unsupported planned-stack claims. **Done when:** product scope and deliverables agree, and AI-driven mutations cannot bypass approval/safety controls.

10. **Publish operating and support documentation (P2).** Expand the short README with setup, configuration, API/auth model, AWS IAM permissions, data flows, architecture, limitations, incident response, upgrade, and support guidance. **Done when:** a new operator can deploy, validate, recover, and safely disable the service using repository documentation alone.

## Technical debt and production-readiness gaps

- Authentication defaults to permissive development mode unless `CLOUDOPS_ENV=production` is set; production then requires token mode and configured tokens. The token boundary does not itself provide credential lifecycle management.
- Tenant isolation is partial: provider-neutral resources, EC2 list/summary/detail and aggregate insights, and direct S3 bucket routes are filtered by ownership tags, while AWS account credentials are not tenant-scoped. S3 checks require bucket-tag read permission and hide resources when ownership cannot be established.
- Audit actor attribution is implemented for autonomous runs, not consistently for all API operations.
- Persistent audit stores are SQLite local files; there is no shared production database, migration, backup, or restore workflow.
- Real infrastructure mutations are intentionally disabled; planning, governance, and simulation must not be represented as completed remediation.
- `/health` returns static application status and does not establish AWS or persistence readiness.
- No CI workflow, deployment/container configuration, IaC, frontend, or substantive operator documentation was found; `docs/` is empty.
- No supported Python runtime or automated dependency update/security workflow is documented.
- Cost insights are qualitative; live billing/pricing integration is not present.
- The checkout contains untracked SQLite database files. They were left untouched and are not part of this roadmap change.

## Scope and count

This is a finite backlog of ten delivery outcomes, not a claim to enumerate every possible product feature. Items 1–8 cover security, safe execution, and operational readiness; items 9–10 settle product scope and operating documentation. Add numbered work only when deliberately replacing or extending this scope.
