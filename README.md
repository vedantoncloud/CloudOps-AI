# CloudOps AI

CloudOps AI is a cloud operations platform designed to help monitor,
analyze, and manage cloud infrastructure through a secured browser console and API.

## Project Status

Under active development. The FastAPI application serves an authenticated
operations console at `/console` for EC2/S3 inventory, resource governance,
pending approvals, and actor-scoped autonomous run history. In development
auth mode it connects without a token; in token mode, enter a bearer token in
the console. The token is held in page memory and cleared when the page closes.

The console and API show planning and governance information. Infrastructure
mutations remain disabled; action execution is dry-run only.

S3 bucket analysis checks encryption, Public Access Block, whether AWS classifies
the bucket policy as public, public ACL grants, and versioning. The AWS role needs
`s3:GetBucketPolicyStatus` and `s3:GetBucketAcl` for the policy and ACL checks.
Denied or malformed check results are reported as unknown; they are not treated
as evidence that the bucket is private. Buckets using bucket-owner-enforced
Object Ownership have ACL checks reported as disabled.

Bucket analysis also reports S3 Object Lock enablement and any default
governance or compliance retention rule. Grant `s3:GetBucketObjectLockConfiguration`
to the AWS role for this read-only check. An enabled bucket without a default
retention rule is shown distinctly from a bucket without Object Lock.

## API access control

The assembled API supports two access modes. For local development, set
`CLOUDOPS_AUTH_MODE=development`; this mode allows requests without credentials
and labels them as the `local-development` principal in the `local` tenant.
The application defaults to this mode when the variable is unset, so it must
not be used for a network exposed deployment.

For a token protected deployment, set `CLOUDOPS_AUTH_MODE=token` and provide
`CLOUDOPS_API_TOKENS` as a JSON object mapping bearer tokens to claims. For
example:

```json
{"replace-with-a-secret":{"subject":"operator-1","role":"operator","tenant_id":"account-1"}}
```

Supported roles are `reader`, `operator`, and `admin`. GET and HEAD requests
require `reader`; other methods require `operator`. Requests may include
`X-Cloud-Tenant`, which must match the authenticated token's `tenant_id`.
Keep token values in a deployment secret store and use an identity provider or
gateway to issue, rotate, and revoke them. The boundary attaches the principal
and tenant to request state, and autonomous-run lifecycle and verification
events record the authenticated subject as their actor. In token mode, the
provider-neutral `/autonomy/resources` inventory and governance routes only
return resources tagged `CloudOpsTenantId` with the token's `tenant_id`; missing
or mismatched ownership tags are hidden as not found for governance lookups.
Direct EC2 and S3 inventory and resource routes also enforce tenant ownership
using the `CloudOpsTenantId` tag. Configure `CLOUDOPS_TENANT_AWS_ROLES` as a
JSON object mapping tenant IDs to IAM role ARNs to route each tenant's AWS
calls through its own account role. Assumed credentials are cached until near
expiry, and a failed role assumption never falls back to the process identity.
For compatibility, tenants without a mapping use the process AWS identity by
default. Set `CLOUDOPS_REQUIRE_TENANT_AWS_ROLE=true` to fail closed when any
authenticated tenant has no configured role; the setting defaults to `false`.

## Runtime

- FastAPI
- AWS

The API applies a per-process fixed-window request limit of 120 requests per
authenticated subject (or client address before authentication) per 60 seconds.
Set `CLOUDOPS_RATE_LIMIT_REQUESTS` and `CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS` to
positive integers to adjust it. Exceeded limits return HTTP 429 with a
`Retry-After` header. Each application process tracks its own counters; use a
shared gateway or limiter when a deployment needs a cluster-wide quota.

## Health and telemetry

Use `GET /health` as a liveness check. It confirms that the API process can
serve a request; it does not check AWS or the local stores. Use `GET /ready`
before routing traffic to a process. Readiness checks AWS and the configured
persistent stores and returns a sanitized unavailable response when a required
dependency is unhealthy. Both probes are public so deployment platforms can
call them without an API token.

In token mode, `GET /metrics` requires an `admin` bearer token. It exposes
Prometheus text format with `cloudops_http_requests_total` and
`cloudops_http_request_duration_seconds` counters/histograms. Labels contain
the normalized HTTP method, FastAPI route template, and status code; they do
not contain request paths with resource IDs, tenant IDs, or error text. The
latency histogram uses fixed buckets from 5 ms through 5 seconds and includes
the `+Inf` bucket. Metrics are held in process memory, are cumulative since
process start, and reset on restart. Each replica has its own values.

Configure Prometheus to read an admin token from a protected file:

```yaml
scrape_configs:
  - job_name: cloudops-ai
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /run/secrets/cloudops-metrics-token
    static_configs:
      - targets: ["cloudops-ai:8000"]
```

Treat the scrape credential as a secret and grant it only to the monitoring
system. For multi-replica deployments, scrape each process separately; this
endpoint does not aggregate across replicas. A basic request failure ratio
query over five minutes is:

```promql
sum(rate(cloudops_http_requests_total{status=~"5.."}[5m]))
/ clamp_min(sum(rate(cloudops_http_requests_total[5m])), 1)
```

To estimate the 95th percentile request latency from the fixed buckets:

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(cloudops_http_request_duration_seconds_bucket[5m]))
)
```

The authenticated Operations console shows cumulative server-side HTTP
failures, AWS operation failures, and audit/idempotency SQLite operation
outcomes. These summaries are process-local and reset on restart. They contain
fixed operation/route labels and counts, not provider errors, SQL, database
paths, or audit content. Request logs include a correlation ID, method, path,
status, and duration; they omit headers and request/response bodies. Use the
response `X-Request-ID` value to locate the matching log entry.

GitOps change sets and their lifecycle state are stored in SQLite so proposals,
approvals, dry-run applies, and verification results survive process restarts.
The default file is `backend/gitops_changes.db`; set
`CLOUDOPS_GITOPS_DB_PATH` to place it elsewhere. `/ready` checks this store.
Corrupt stored change data fails startup rather than silently dropping pending
reviews. This is local-file durability for a single process, not shared database
or multi-process coordination. Back up this file with the audit and action-plan
stores. Real infrastructure mutation remains disabled.

The console is a small browser client served directly by FastAPI. Shared
production persistence, container deployment, CI, infrastructure as code, and
LLM integration are not currently provided.
