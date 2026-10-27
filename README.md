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

EC2 instance details include attached security-group ingress and egress rules
and their IPv4/IPv6 CIDR, prefix-list, and security-group sources or destinations.
Token-mode requests verify instance tenant ownership before reading those rules.
The AWS role needs `ec2:DescribeInstances` and `ec2:DescribeSecurityGroups` for
this read-only view.

The console also lists regional EBS volumes, including unattached volumes, size,
type, encryption and KMS key, performance settings, tags, and attachments. The
unattached-only filter is applied by EC2 before pagination, and results can be
exported as CSV. In token mode, only volumes tagged with the caller's
`CloudOpsTenantId` are returned. Grant `ec2:DescribeVolumes` to the AWS role.

Operators can also review account-owned EBS snapshots by region, including source volume, creation time, size, encryption and KMS key, description, and tags, with pagination and CSV export. In token mode, only snapshots tagged with the caller's `CloudOpsTenantId` are returned. Grant `ec2:DescribeSnapshots` to the AWS role. This is an inventory view; it does not create or delete snapshots.

Operators can inspect paginated RDS DB instance inventory with engine/version,
status, instance class, allocated storage, encryption, Multi-AZ setting,
availability zone, and connection endpoint. In token mode, each instance's
`CloudOpsTenantId` tag is verified before it is returned; if tag access fails,
the request fails closed. In the Operations console, choose **Inspect RDS
instances** to browse the selected region, continue through provider pages, and
review public accessibility, backup retention, and deletion protection, and
export loaded results as a spreadsheet-safe CSV. A missing AWS posture field is
shown as unknown rather than assumed safe. The API is
`GET /cloud/aws/rds/instances` and accepts
an optional `region`, `max_records` (20–100), and continuation `marker`. Grant
the AWS role `rds:DescribeDBInstances` and `rds:ListTagsForResource`. This is a
read-only inventory; it does not connect to databases or expose credentials.

The Operations console also exposes regional RDS automated and manual recovery
snapshots, including database, engine, status, type, creation time, size,
encryption and KMS key, with marker pagination and CSV export. In token mode,
snapshots are returned only when their `CloudOpsTenantId` tag matches the caller;
tag lookup failures fail closed. The API is `GET /cloud/aws/rds/snapshots` and
accepts the same optional `region`, `max_records` (20–100), and continuation
`marker` parameters. Grant `rds:DescribeDBSnapshots` and
`rds:ListTagsForResource` to the AWS role. This is read-only inventory and does
not create or restore snapshots.

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
audit event feed and NDJSON export are restricted to the authenticated actor
and tenant; events without tenant attribution remain hidden from tenant users,
while administrators retain shared audit visibility. The
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
authenticated tenant has no configured role. The setting defaults to `true`
when `CLOUDOPS_ENV=production` and `false` otherwise; an explicit
`CLOUDOPS_REQUIRE_TENANT_AWS_ROLE` value overrides that default. Configure a
role for every tenant before routing tenant AWS requests in production.

## Runtime

- Python 3.13
- FastAPI
- AWS

## Development and tests

From the repository root, install the pinned backend dependencies and run the
backend suite:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests
```

GitHub Actions runs this suite on pushes and pull requests with Python 3.13.

## Container deployment

Build the production image from the repository root:

```sh
docker build -t cloudops-ai:latest .
```

The image runs as an unprivileged `cloudops` user, listens on port 8000, and
defaults to `CLOUDOPS_ENV=production` and `CLOUDOPS_AUTH_MODE=token`. It exits
at startup if token credentials are missing or invalid. Provide a protected
runtime environment file outside the repository, then start it with a durable
volume for audit, idempotency, action-plan, and GitOps state:

```sh
docker volume create cloudops-data
docker run -d --name cloudops-ai --restart unless-stopped \
  --env-file /secure/path/cloudops-ai.env \
  -p 127.0.0.1:8000:8000 \
  -v cloudops-data:/var/lib/cloudops \
  cloudops-ai:latest
```

The environment file must define `CLOUDOPS_API_TOKENS` as the JSON token
registry and `CLOUDOPS_TENANT_AWS_ROLES` as the tenant-to-role ARN map. Set
`AWS_DEFAULT_REGION` for the deployment. In production, tenant AWS requests
fail closed when a tenant has no role mapping. Supply AWS credentials through
the host's workload identity mechanism (such as an ECS task role or EC2
instance profile); avoid baking credentials into the image. The container
stores its four SQLite databases in `/var/lib/cloudops`, so keep the named
volume across upgrades and back it up using the documented admin backup APIs.
Terminate TLS at a trusted reverse proxy and expose the container only on a
private interface; the sample port binding is loopback-only. `GET /health` is
the liveness probe and `GET /ready` checks AWS and persistent-store readiness.

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

## Audit chain export, verification, and recovery

Administrators can download the complete persisted audit chain from the Audit
tab or `GET /autonomy/audit/chain/export`. This endpoint is admin-only and
returns one full-chain JSON snapshot; it does not apply the filters used by the
matching-event NDJSON export. Keep the export and its final hash outside the
application host. Verify a downloaded file with the standard-library tool:

```powershell
python backend/verify_audit_chain.py cloudops-audit-chain.json
```

The verifier checks the export format, ordered event sequence, previous-hash
links, each event's canonical JSON SHA-256 hash, and the final hash. A valid
result proves that the downloaded events match the chain represented by that
file. Sequence numbers identify stored order; the hashes cover event content
and chain order. It does not prove who created the file or when: anyone able
to rewrite the SQLite database can change events and recompute the entire
chain. For an independent checkpoint, record the final hash and event count
in a separately controlled system after each export (for example, a signed
release record or immutable storage account with separate credentials).
Compare later exports against that checkpoint. Do not keep the only
checkpoint beside the audit database.

Audit events are retained in the configured local SQLite database; CloudOps AI
does not automatically prune them. Set a retention period that meets the
organization's obligations, archive complete verified exports before any
approved deletion, and retain the associated external final-hash checkpoints.
Restrict database and export access to the operations administrators who need
it. The chain detects changes relative to a trusted checkpoint; it cannot
restore deleted or rewritten records by itself.

Administrators can download a consistent snapshot of the live audit database
from `GET /autonomy/audit/database/backup`. The endpoint requires an admin
bearer token, opens the configured database read-only, uses SQLite's online
backup API, checks the snapshot with `PRAGMA integrity_check`, and streams the
file without retaining a server-side copy. The same admin-only API provides
`GET /autonomy/audit/database/backup/action-plans` and
`GET /autonomy/audit/database/backup/gitops` for the durable action-plan and
GitOps stores. Each store is snapshotted independently; the API does not create
a cross-database transaction. Store downloads separately with access controls;
temporary snapshots are removed after streaming.

Store backups separately with access controls and a tested restore window. To
recover, stop the service, preserve the damaged database as evidence, restore
the selected backup to the configured database path, restart, and verify
readiness. Export and independently verify the restored chain, then compare
its final hash and event count with the most recent external checkpoint. If
they differ, preserve both copies and investigate before resuming normal audit
operations; do not silently replace the checkpoint or rewrite the chain.

Before an incident, run a non-destructive restore drill against each downloaded
backup. The tool checks SQLite integrity, loads the store using the application's
own persistence code in an isolated temporary copy, and verifies the audit hash
chain. It never opens the supplied backup for writing:

```powershell
python backend/verify_database_backup.py audit path\to\cloudops-audit-backup.db
python backend/verify_database_backup.py action-plans path\to\cloudops-action-plans-backup.db
python backend/verify_database_backup.py gitops path\to\cloudops-gitops-backup.db
```

A successful drill prints JSON with `status: ok` and the number of records
loaded. A failed integrity, schema, deserialization, or audit-chain check exits
with status 1 and a concise diagnostic. A successful drill validates a backup
copy; it does not replace a production restore rehearsal or verify external
checkpoints and application readiness.

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
