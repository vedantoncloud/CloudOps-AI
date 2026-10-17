# CloudOps AI Roadmap

**Repository audit:** 2026-10-17, updated after adding admin-only AWS account billing to the operations console. This roadmap contains **9 remaining tasks**: the nine numbered incomplete outcomes below. Sub-bullets and acceptance criteria do not count separately. Recount only when a complete outcome ships or scope is explicitly changed.

## Current state

CloudOps AI is a FastAPI backend with AWS EC2/S3 inventory and insight routes, planning and governance systems, approval workflows, dry-run execution, recovery, provider abstractions, and audit capabilities. The history shows sustained feature and hardening work, especially around persistent audit idempotency/reconciliation, governance contracts, and audit integrity. There are **305 `test_*.py` modules** under `backend/tests`; this is a file count, not a test-case count or a claim that they pass. The test suite was not run during this repository audit.

Recent commits added configurable bearer-token access control, admin-only audit diagnostics, autonomous-run audit attribution, provider-neutral resource tenant filtering, and tenant filtering for EC2 inventory/summary/detail and aggregate insights. In token mode, the `CloudOpsTenantId` tag scopes provider-neutral `/autonomy/resources` inventory/governance, EC2 inventory/summary/detail/aggregate insights, and direct S3 bucket inventory/detail/object/insight routes. S3 bucket access fails closed when its ownership tag cannot be read; deployments need `s3:GetBucketTagging` for those checks. Tenant users also receive sanitized responses from AWS status and service health checks; admins retain diagnostics. The AWS client/account context is shared rather than selected by tenant. Development remains the default environment and authentication mode, but `CLOUDOPS_ENV=production` now requires token mode and a nonempty token registry at startup. Tokens and claim validation exist; token issuance, rotation, revocation, and federation remain upstream responsibilities. Autonomous-run events include the authenticated subject; attribution is not consistently wired through other operations.

The audit trail and idempotency/reconciliation state persist to SQLite files and have substantial validation and concurrency coverage. This is not a shared production database architecture. `ActionExecutor` rejects real infrastructure execution; execution remains dry-run only. Autonomous lifecycle audit events now back an authenticated, actor-scoped, paginated `/autonomy/runs` history endpoint. `/console` serves a lightweight authenticated browser console for inventory, governance, approvals, and run history. EC2 instance details include accessible CPU and network trend charts alongside the underlying CloudWatch samples. The repository has a README and roadmap, but `docs/` is empty. No Docker/container setup, CI workflow, Terraform/Kubernetes configuration, migration framework, or LLM integration was found. Requirements are pinned, but no supported Python version is documented. EC2/S3 cost insights remain qualitative, while administrators can inspect shared-account daily billing totals through Cost Explorer.

Administrators can also view the shared AWS account's last 30 complete days of daily unblended spend and service-level totals through Cost Explorer in the console. This endpoint is admin-only because the AWS account and billing data are shared; it does not provide tenant- or resource-level charge attribution.

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
- Authenticated tenant users receive a sanitized AWS status response without the shared AWS account ID, principal ARN, or raw diagnostics; admins retain full status details.
- Authenticated tenant users receive sanitized AWS service health responses without raw shared-account SDK errors; admins retain full diagnostics.
- Authenticated users can retrieve an individual EC2 inventory record through `GET /cloud/aws/ec2/instances/{instance_id}` using a direct instance lookup, independent of inventory pagination; token-mode results hide foreign, untagged, and missing IDs uniformly.
- Operators can inspect CPU utilization and inbound/outbound network trends as accessible charts in EC2 details, with latest/peak summaries and explicit empty states when CloudWatch has no datapoints.
- Tenant-scoped EC2 detail, metrics, status, and insight checks look up the requested instance directly, so ownership checks work for instances beyond the first inventory page.
- Tenant-scoped EC2 action-plan creation checks ownership with a direct instance lookup, so operators can create plans for owned instances beyond the first inventory page.
- Authenticated operators can list their durable autonomous run history through `/autonomy/runs`, with lifecycle summaries and bounded pagination.
- Authenticated operators can inspect an individual run's lifecycle events and recorded evidence from the console; run detail is restricted to the authenticated actor and hides foreign or missing runs uniformly.
- Authenticated users can browse the in-memory action-plan queue through `/autonomy/plans`, filter by lifecycle status, and page through results; token-mode plan access is restricted to the tenant that created each plan.
- Non-admin authenticated users can list and export only their own audit events; admins retain cross-actor audit access.
- Operators can browse a tenant-scoped, newest-first pending approval queue through `/autonomy/approvals`, with bounded pagination.
- Operators can filter the tenant-scoped action plan queue by status, risk, and resource type; filtered totals and pagination stay consistent when filters change in the console.
- Operators can search the action plan queue case-insensitively by action type, target resource ID, or reason; search composes with status/risk/resource filters and keeps totals and pagination consistent.
- Operators can reject a pending action plan with a required reason; the response records the authenticated reviewer and exposes a distinct `rejected` status.
- Operators can cancel a pending action plan with the authenticated actor recorded as its decision maker, matching approval and rejection attribution in plan state.
- Authenticated users can retrieve an action plan's current state through `GET /autonomy/plans/{action_id}`; token-mode lookups hide plans belonging to another tenant.
- Control-loop evaluation and governance audit events identify the authenticated principal that requested each evaluation.
- Operators can distinguish process liveness (`/health`) from dependency readiness (`/ready`); readiness checks AWS and both persistent SQLite stores, returns 503 when any dependency is unavailable, and does not expose account or error details.
- Authenticated users can resume S3 object listings from an AWS continuation token through `/cloud/aws/s3/buckets/{bucket_name}/objects`; responses expose truncation state and the next token for incremental browsing.
- Authenticated users can resume EC2 inventory listings from an AWS `NextToken` through `/cloud/aws/ec2/instances`; page sizes are bounded from 5 to 1,000 and results preserve tenant filtering.
- Operators can inspect timestamped EC2 CPU and network metric samples over a selectable 1–24 hour window; the API bounds lookback duration and CloudWatch sampling periods.
- Authenticated users can page through S3 bucket inventory with bounded `MaxBuckets` and AWS continuation tokens; the console can continue bucket pages, and tenant ownership filtering applies to each page.
- S3 bucket inventory defaults to a bounded 1,000-bucket AWS page and always returns continuation metadata, including when clients omit pagination parameters.
- Authenticated users can use `/console` to browse EC2/S3 inventory, inspect resource governance, review and decide pending approvals, and view their autonomous run history; bearer credentials stay in page memory.
- Token-scoped EC2/S3 plan generation verifies the source resource's tenant ownership first; foreign, untagged, missing, or unverifiable resources are hidden before insight analysis.
- The operations console can create action plans from EC2/S3 resource insights, browse and filter the plan queue, evaluate plans, cancel eligible plans, and run approved plans in dry-run mode.
- The operations console can browse S3 bucket objects by prefix, choose a bounded page size, and continue through truncated listings.
- Operators can navigate S3 bucket folder prefixes in the console; delimiter-based listings show common prefixes as folders, support moving up one level, and retain bounded continuation pagination.
- The operations console appends subsequent S3 object pages to the visible listing, reports the cumulative loaded count, and preserves earlier results if a later page fails.
- Operators can inspect S3 object metadata from the console, including size, content type, ETag, storage class, encryption, modification time, and user metadata; the lookup uses `HeadObject` and enforces the bucket tenant boundary.
- Operators can download S3 objects from the console through five-minute presigned attachment URLs; URL issuance enforces the bucket tenant boundary.
- The operations console can analyze an S3 bucket by optional prefix, showing object statistics, storage health, security findings, cost opportunities, and largest objects from bounded scans of up to 1,000 objects; each analysis result reports failures independently.
- The operations console can page through action plans in batches of 50, append older plans, and reset pagination when the status filter or refresh changes.
- Operators can search the EC2 or S3 inventory rows already loaded across pages without reloading page one or losing the continuation cursor.
- Authenticated users can page through EC2 inventory with bounded AWS `MaxResults` and opaque `NextToken` cursors; each page applies tenant ownership filtering before returning instances.
- Operators can filter EC2 inventory by AWS tag key and value in the operations console; the filter is applied server-side and retained when loading subsequent pages.
- Operators can filter EC2 inventory by the exact AWS Name tag in the operations console; AWS applies the filter and subsequent pages retain it.
- Operators can inspect a plan from the console queue and retrieve its current tenant-scoped state, including the full plan details.
- The operations console can load EC2 fleet efficiency, cost, rightsizing, and security insights from the aggregate APIs; token-mode analysis is limited to authenticated-tenant instances.
- Authenticated users can browse audit history in the operations console, filter events by resource ID, and load additional bounded pages through the actor-scoped audit API.
- Operators can page through the pending approval queue and authenticated users can page through their autonomous run history in the operations console, with bounded requests, visible totals, and independent pagination state.
- Authenticated users can download the complete audit feed matching the console's resource filter as newline-delimited JSON; the export request retains bearer authentication and server-enforced actor scope.
- The operations console can open EC2 inventory and metrics or S3 bucket details and insights from each resource row, with independent error reporting when one detail request fails.
- Operators can download the loaded EC2 or S3 inventory pages as search-aware CSV, with correctly quoted cells and spreadsheet formula-injection protection.
- Operators can filter audit history by a local start/end time range; the console converts the selected times to UTC and applies the same range to paged results and JSONL export.
- Authenticated users can filter audit history by actor ID in the operations console; the filter applies to paged results and JSONL export while the API enforces self-only visibility for non-admins.
- Operators can filter audit history by exact event type in the operations console; the filter applies to both paged results and JSONL export.
- GitOps change sets created by token-authenticated control-loop requests are tenant-owned; listing, detail, approval, rejection, apply, and verification enforce that ownership, while approval/rejection attribution comes from the authenticated principal.
- The operations console shows per-instance EC2 insights beside inventory and selectable-window metrics, with independent error reporting for each detail request.
- EC2 and S3 action-plan generation uses `POST` because it creates plan records; token-mode readers are denied and operators can create tenant-scoped plans.
- S3 object-list API requests default to a bounded 1,000-object page and expose AWS continuation state, so ordinary browser/API requests do not scan an entire bucket.
- Administrators can view the shared AWS account's total daily unblended cost for the last 30 complete days in the console; the account-level endpoint is admin-only in token mode and reports billing permission or availability failures without exposing SDK details.
- Administrators can see the last 30 complete days of unblended spend aggregated by AWS service, ranked by total cost, alongside the daily account totals in the billing console response.

## Prioritized remaining work

1. **Complete API authorization, tenant isolation, and attribution (P0).** Extend resource ownership enforcement to every tenant-sensitive direct AWS inventory, detail, metric, and insight route; establish tenant-specific AWS account/credential boundaries; verify access rules across privileged operations; consistently attach the authenticated principal to audit events. Define and operate token issuance, rotation, revocation, and external identity integration. **Done when:** every protected route has an explicit tested authorization policy, cross-tenant reads are prevented across all AWS/resource routes and account boundaries, and operational audit events identify their actor.

2. **Adopt a production persistence architecture (P0).** Select a supported shared database for operational state and audit/idempotency records. Provide schema migrations, transaction and locking behavior, backup/restore, retention, and upgrade procedures. Existing SQLite persistence is local-file durability, not shared database support. **Done when:** clean installation and upgrades work against the chosen database, restart/concurrency behavior is verified, and restore/retention procedures are documented and exercised.

3. **Keep infrastructure execution safely disabled until a scoped action is ready (P0).** Real mutations are currently rejected. If enabling execution, start with explicitly selected reversible AWS actions and implement least-privilege permissions, fresh precondition checks, approval binding, idempotency, bounded retries, verification, and tested rollback. **Done when:** every enabled mutation has an action-specific safety review and integration coverage; all unimplemented mutations remain denied. If no real-action scope is approved, document dry-run-only operation as the supported release behavior.

4. **Provide deployment and environment configuration (P1).** Production startup validation now requires token auth and configured credentials. Remaining work: add a reproducible runtime/container setup, broader configuration validation, secret injection guidance, TLS/reverse-proxy expectations, and documented development/staging/production settings. **Done when:** a documented clean deployment starts without source edits and rejects unsafe or missing production configuration.

5. **Add automated CI quality gates (P1).** Define supported Python versions and add dependency installation, test execution, lint/type checks, and dependency/security scanning with actionable failure output. **Done when:** pull requests run the documented gates and report failures reliably.

6. **Make health and operations observable (P1).** `/health` now provides liveness and `/ready` reports AWS dependency readiness with sanitized responses. Add structured logs, request correlation, metrics, database readiness, and actionable AWS/database failure signals without exposing secrets or sensitive audit payloads. **Done when:** operators can distinguish application health from dependency health and diagnose failures using documented telemetry.

7. **Harden API and AWS operational limits (P1).** Set request/response size limits, pagination bounds beyond EC2 inventory, S3 bucket inventory, and S3 object listing, timeouts, rate limits, AWS retry/backoff and throttling behavior, and consistent error contracts. **Done when:** limits are explicit and covered for malformed, oversized, throttled, and unavailable-dependency conditions.

8. **Specify audit trust, retention, and recovery guarantees (P1).** Document the hash-chain threat model and external key/anchor strategy; define tamper detection, export verification, retention, access, backup, and disaster recovery. A hash chain stored in a writable database cannot by itself prevent an attacker with full store access from rewriting the history and recomputing the chain. **Done when:** an operator can independently verify exported history and follow tested backup/restore and incident procedures.



9. **Publish operating and support documentation (P2).** Expand the short README with setup, configuration, API/auth model, AWS IAM permissions, data flows, architecture, limitations, incident response, upgrade, and support guidance. **Done when:** a new operator can deploy, validate, recover, and safely disable the service using repository documentation alone.

## Technical debt and production-readiness gaps

- Authentication defaults to permissive development mode unless `CLOUDOPS_ENV=production` is set; production then requires token mode and configured tokens. The token boundary does not itself provide credential lifecycle management.
- Tenant isolation is partial: provider-neutral resources, EC2 list/summary/detail and aggregate insights, direct S3 bucket routes, and GitOps change sets created through the authenticated control loop are tenant-scoped, while AWS account credentials are not tenant-scoped. S3 checks require bucket-tag read permission and hide resources when ownership cannot be established. The shared AWS account identity remains available to admins through `/cloud/aws/status`.
- Audit actor attribution is implemented for autonomous runs, approval/rejection/cancellation plan state, and control-loop evaluations, but not consistently for all API operations. Audit event listing/export is actor-scoped for non-admin users; the underlying shared trail and operational diagnostics still require broader tenant and attribution work.
- Persistent audit stores are SQLite local files; there is no shared production database, migration, backup, or restore workflow.
- Real infrastructure mutations are intentionally disabled; planning, governance, and simulation must not be represented as completed remediation.
- `/health` remains a static liveness check; `/ready` checks AWS and configured persistence stores but does not yet provide structured logs, request correlation, metrics, or actionable diagnostic signals.
- No CI workflow, deployment/container configuration, IaC, or substantive operator documentation was found; `docs/` is empty. The console is a lightweight browser client served by FastAPI, with inventory/governance, plan generation, inspection and review, approvals, and run history.
- No supported Python runtime or automated dependency update/security workflow is documented.
- EC2/S3 optimization insights remain qualitative and do not attribute Cost Explorer charges to tenants or individual resources; the admin-only account billing view reports daily shared-account totals.
- The checkout contains untracked SQLite database files. They were left untouched and are not part of this roadmap change.

## Scope and count

This is a finite backlog of nine remaining delivery outcomes, not a claim to enumerate every possible product feature. Items 1–8 cover security, safe execution, and operational readiness; item 9 covers operating documentation. Add numbered work only when deliberately replacing or extending this scope.
