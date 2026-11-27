# CloudOps AI

CloudOps AI is a cloud operations platform designed to help monitor,
analyze, and manage cloud infrastructure through a secured browser console and API.

## Project Status

**Portfolio milestone — 28 November 2026.** The current `main` branch
includes the authenticated FastAPI operations console at `/console` for
EC2/S3 inventory, resource governance, pending approvals, and actor-scoped
autonomous run history. In development auth mode it connects without a token;
in token mode, enter a bearer token in the console. The token is held in page
memory and cleared when the page closes.

The verified `main` commit is `4ef14c3` (PR #177, local Docker Compose
workflow). Its post-merge CI run
[#46051732942](https://github.com/vedantoncloud/CloudOps-AI/actions/runs/46051732942)
passed all three jobs: backend tests and production-container smoke tests,
MySQL 8.4 migrations and MySQL-backed production-container smoke tests, and
the pinned dependency audit. Recent security and developer-experience updates
also include sanitized operational failure logging (PR #172), local audit
database ignore rules (PR #173), a Content Security Policy with externalized
console assets (PR #175 and #176), and the local Compose workflow (PR #177).
These are CI integration checks, not evidence of a live multi-replica
deployment or a MySQL backup/restore rehearsal.

This is a portfolio/demo-ready milestone, not a claim of a live AWS production
deployment. The console and API show planning and governance information.
Infrastructure mutations remain disabled; action execution is dry-run only.

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

## AWS IAM permission reference

The AWS integration currently performs read-only inventory, posture, metrics, alarm,
and cost queries, plus `sts:AssumeRole` when tenant role mappings are configured.
The following actions map the SDK operations used by
`backend/services/aws_service.py`; they are not a general-purpose AWS policy.

| Feature | IAM actions used | Resource scope guidance |
| --- | --- | --- |
| Tenant role assumption | `sts:AssumeRole` | Restrict the application principal's identity policy to the exact tenant role ARNs it must assume. In each target role's trust policy, trust only the dedicated application principal and require that tenant's exact ExternalId. ExternalId is a trust-policy condition, not a substitute for restricting the role ARN. |
| Caller identity | No IAM allow action required for `sts:GetCallerIdentity` | AWS documents that this operation requires no permission, even when explicitly denied. |
| EC2 inventory and details | `ec2:DescribeRegions`, `ec2:DescribeInstances`, `ec2:DescribeVolumes`, `ec2:DescribeSnapshots`, `ec2:DescribeSecurityGroups`, `ec2:DescribeInstanceStatus` | These Describe operations do not expose resource-level authorization in the EC2 service authorization reference; use `Resource: "*"` for these actions. |
| RDS inventory and ownership tags | `rds:DescribeDBInstances`, `rds:DescribeDBSnapshots`, `rds:ListTagsForResource` | Where supported by the action's authorization model, scope to the relevant DB instance and DB snapshot ARNs. Validate the exact resource types and conditions against the current RDS authorization reference before deploying a restrictive policy. |
| S3 bucket discovery | `s3:ListAllMyBuckets`, `s3:GetBucketLocation` | `s3:ListAllMyBuckets` requires `Resource: "*"`. Scope `s3:GetBucketLocation` to the required bucket ARNs. |
| S3 bucket configuration and posture | `s3:GetBucketVersioning`, `s3:GetLifecycleConfiguration`, `s3:GetReplicationConfiguration`, `s3:GetBucketLogging`, `s3:GetEncryptionConfiguration`, `s3:GetBucketObjectLockConfiguration`, `s3:GetBucketTagging`, `s3:GetBucketPolicy`, `s3:GetBucketPolicyStatus`, `s3:GetBucketAcl`, `s3:GetBucketPublicAccessBlock` | Scope bucket-level actions to `arn:aws:s3:::bucket-name` for only the buckets assigned to that tenant. |
| S3 object inventory and versions | `s3:ListBucket`, `s3:ListBucketVersions` | Scope list actions to the assigned bucket ARNs. |
| S3 object metadata and downloads | `s3:GetObject`, `s3:GetObjectVersion` | Scope to assigned object ARNs such as `arn:aws:s3:::bucket-name/*`. `s3:GetObjectVersion` is needed when metadata or a presigned download targets a specific version ID. The application signer needs the applicable read permission when creating a presigned-download URL. The URL itself is a time-limited bearer credential: anyone who possesses it can use it until it expires, without separate AWS credentials. |
| EC2 metrics and alarms | `cloudwatch:GetMetricStatistics`, `cloudwatch:DescribeAlarms` | `GetMetricStatistics` does not support resource-level permissions and requires `Resource: "*"`. Scope `DescribeAlarms` to alarm ARNs where supported by the CloudWatch authorization reference. |
| Account cost analysis | `ce:GetCostAndUsage` | This endpoint is admin-only because it returns account-level spend. Use the Cost Explorer/Billing View resource model supported by the account; otherwise the action commonly needs `Resource: "*"`. |

This mapping is based on the SDK operations currently present in the service layer.
It deliberately does not grant create, update, delete, start, stop, or other
infrastructure-mutation actions. Tenant ownership tags enforced by the API are
an application authorization boundary; they do not replace IAM permissions or
resource scoping in the target account.

Start with the smallest feature-specific action set and add permissions only
when an enabled endpoint demonstrably needs them. A deployment that disables a
feature can omit its corresponding actions. Test the final policy in a
non-production account: service authorization can vary by resource type,
region, account configuration, and dependent permissions. Do not use
`AdministratorAccess` as a troubleshooting shortcut.

Official references:
- [EC2 service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ec2.html)
- [S3 service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html)
- [RDS service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_rds.html)
- [CloudWatch service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudwatch.html)
- [Cost Explorer service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ce.html)
- [STS service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sts.html)
- [STS GetCallerIdentity API](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)
- [AWS third-party role access and ExternalId guidance](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html)
- [IAM Principal element and role-principal behavior](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_principal.html)

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
{"replace-with-a-secret":{"subject":"operator-1","role":"operator","tenant_id":"account-1","exp":4102444800}}
```

Supported roles are `reader`, `operator`, `admin`, and `platform_admin`. GET and HEAD requests
require `reader`; other methods require `operator`. Administrator-only routes require
`admin` or `platform_admin`. Shared audit-store diagnostics, reconciliation,
integrity export, and database backup routes require the explicit
`platform_admin` role; a tenant `admin` cannot access those cross-tenant stores.
A platform-admin token must still carry a configured `tenant_id`: AWS request
context remains bound to that tenant and does not become global AWS access.
Requests may include
`X-Cloud-Tenant`, which must match the authenticated token's `tenant_id`.

The `exp` claim is a Unix timestamp in seconds and is checked on every
authenticated request. Expired tokens receive HTTP 401 with a Bearer challenge.
For example, the value above expires at 2100-01-01T00:00:00Z. Staging and
production require every configured token to include `exp` by default; startup
fails closed if any token omits it. Development keeps the legacy non-expiring
behaviour. For a controlled migration only, set
`CLOUDOPS_REQUIRE_TOKEN_EXPIRATION=false` to temporarily accept legacy tokens
in staging or production, then remove the override after all credentials have
expiry timestamps. Set it to `true` to enforce expiry in any token-mode
environment. Invalid values fail startup. This registry validates and enforces
configured credentials but does not issue or persist tokens, and changing the
registry still requires a controlled configuration update/restart.
Keep token values in a deployment secret store and use an identity provider or
gateway to issue, rotate, and revoke them. The boundary attaches the principal
and tenant to request state, and autonomous-run lifecycle and verification
events record the authenticated subject as their actor. In token mode, the
audit event feed and NDJSON export are restricted to the authenticated actor
and tenant; events without tenant attribution remain hidden from tenant users,
while tenant administrators remain restricted to their own tenant. Shared audit-store diagnostics and exports require the explicit `platform_admin` role. The
provider-neutral `/autonomy/resources` inventory and governance routes only
return resources tagged `CloudOpsTenantId` with the token's `tenant_id`; missing
or mismatched ownership tags are hidden as not found for governance lookups.
Direct EC2 and S3 inventory and resource routes also enforce tenant ownership
using the `CloudOpsTenantId` tag. Configure `CLOUDOPS_TENANT_AWS_ROLES` as a
JSON object mapping tenant IDs to IAM role ARNs to route each tenant's AWS
calls through its own account role. For cross-account deployments, entries should use the object form:
{"role_arn":"arn:aws:iam::123456789012:role/tenant-a",
"external_id":"a-unique-per-tenant-value"}. The ExternalId is sent to STS and
included in the assumed-session cache identity. Require that exact value in
the target role's trust policy. Use a different, randomly generated ExternalId
for each tenant/customer account. An ExternalId is not a secret and must not be
treated as an authentication credential; its purpose is to mitigate the
cross-account confused deputy problem. Keep the tenant-to-role mapping in
controlled deployment configuration.

Legacy ARN string entries remain supported for compatibility, but they do not
send an ExternalId. Do not use this legacy form for a third-party multi-tenant
cross-account integration: migrate those entries to the object form and update
the target trust policies to require the matching ExternalId. A trust policy
that does not require it does not get confused-deputy protection from this
mechanism. Assumed credentials are cached until near expiry, and a failed role
assumption never falls back to the process identity.

For each target-account role, the trust policy should name only the exact
CloudOps-AI workload role as its AWS principal and require the tenant-specific
ExternalId. Replace the example values below; install this policy on the role
in the tenant's AWS account:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::111122223333:role/cloudops-runtime"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "replace-with-this-tenants-unique-external-id"
        }
      }
    }
  ]
}
```

The CloudOps-AI workload role in the caller account must also have an
identity-based policy allowing sts:AssumeRole on only the tenant role ARNs it
needs. Do not use a wildcard principal or wildcard ExternalId in the target
trust policy. Verify that the intended caller succeeds with the correct
ExternalId and is denied when the ExternalId is missing or incorrect. AWS
binds a directly named IAM role principal to that role's unique principal ID;
if the workload role is deleted and recreated, update the target trust policy
to reference the new role.
For compatibility, tenants without a mapping use the process AWS identity by
default. Set `CLOUDOPS_REQUIRE_TENANT_AWS_ROLE=true` to fail closed when any
authenticated tenant has no configured role. The setting defaults to `true`
when `CLOUDOPS_ENV=staging` or `CLOUDOPS_ENV=production`, and `false` in
development; an explicit `CLOUDOPS_REQUIRE_TENANT_AWS_ROLE` value overrides
that default. Configure a role for every tenant before routing tenant AWS
requests in staging or production.

Credential parsing fails closed: duplicate JSON keys in `CLOUDOPS_API_TOKENS`
and token keys containing whitespace are rejected at startup. Requests must
present exactly one well-formed `Authorization: Bearer ...` header; duplicate
or malformed authorization headers receive HTTP 401. Request bodies with
duplicate or invalid `Content-Length` fields, or conflicting
`Content-Length` and `Transfer-Encoding` metadata, are rejected before
handlers run.

The application adds browser security response headers, including
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a restrictive
`Permissions-Policy`, `Referrer-Policy`, same-origin resource policy, and
`Cache-Control: no-store`. HSTS is added only when the ASGI request scheme is
HTTPS; the service does not impose HSTS on sibling subdomains.

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

## Local development with Docker Compose

For a local-only development instance, copy the safe example environment file
and start the service:

```sh
cp .env.example .env
docker compose up --build
```

Open the console at [http://localhost:8000/console](http://localhost:8000/console).
The Compose service binds to loopback only and persists local SQLite state in
the `cloudops-data` named volume. This profile deliberately enables the
development authentication mode, which grants local admin access without a
token. Use it only on your own machine; do not expose this configuration to a
network or use it for staging or production. The production image defaults to
token authentication, and the production deployment instructions below remain
separate.

Stop the service with `docker compose down`. This preserves the named data
volume; `docker compose down --volumes` deletes that local persistent state.

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
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --pids-limit=128 \
  --env-file /secure/path/cloudops-ai.env \
  -p 127.0.0.1:8000:8000 \
  -v cloudops-data:/var/lib/cloudops \
  cloudops-ai:latest
```

The example also makes the container root filesystem read-only, gives `/tmp`
a small non-executable temporary filesystem, drops all Linux capabilities,
prevents privilege escalation, and limits the process count. The named data
volume remains writable for SQLite state. Keep the Docker daemon and its
socket restricted to trusted operators; container flags do not replace host
isolation or a dedicated workload identity.

The environment file must define `CLOUDOPS_API_TOKENS` as the JSON token
registry and `CLOUDOPS_TENANT_AWS_ROLES` as the tenant-to-role ARN map. Set
`AWS_DEFAULT_REGION` for the deployment. In production, tenant AWS requests
fail closed when a tenant has no role mapping. Supply AWS credentials through
the host's workload identity mechanism (such as an ECS task role or EC2
instance profile); avoid baking credentials into the image. When `CLOUDOPS_DATABASE_URL` is unset, the container stores its four
SQLite databases in `/var/lib/cloudops`; keep the named volume across upgrades
and back up the local stores. When the shared URL is configured, the audit,
idempotency, action-plan, and GitOps stores use that shared SQL database instead
of the legacy SQLite files. See
[shared database deployment and recovery](docs/shared-database-operations.md)
before migrating legacy data or operating a shared database.
Terminate TLS at a trusted reverse proxy and expose the container only on a
private interface; the sample port binding is loopback-only. `GET /health` is
the liveness probe and `GET /ready` checks AWS and persistent-store readiness.

The API applies a fixed-window request limit of 120 requests per
authenticated tenant/principal identity (or client address before
authentication) per 60 seconds. Set `CLOUDOPS_RATE_LIMIT_REQUESTS` and
`CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS` to positive integers to adjust it.
Exceeded limits return HTTP 429 with a `Retry-After` header.

When `CLOUDOPS_DATABASE_URL` is unset, counters are bounded and held in each
process's memory, so each worker enforces its own quota. When the variable is
set to a supported `mysql+pymysql://` or `sqlite:///` URL, all workers using
that database share atomic fixed-window counters through the
`rate_limit_counters` table. SQLite coordinates processes sharing one local
file; it is not a network database for separate hosts. Apply the Alembic
migrations, including migration `0007_shared_rate_limit_counters`, before
starting the application with the shared database URL. Configure the same URL
on every replica. If the shared database or migration is unavailable, requests
receive HTTP 503 rather than falling back to independent process-local limits.
See [shared distributed request rate limiting](docs/distributed-rate-limiting.md)
for deployment details.

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
response `X-Request-ID` value to locate the matching log entry. Unhandled
server exceptions return a generic `500` response with the same request ID;
internal exception details are not sent to API clients.

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

Audit events are retained in the configured persistence backend: the
legacy local SQLite database when `CLOUDOPS_DATABASE_URL` is unset, or the
shared SQL database when it is configured. CloudOps AI does not automatically
prune them. Set a retention period that meets the organization's obligations,
archive complete verified exports before any approved deletion, and retain
the associated external final-hash checkpoints. Restrict database and export
access to the operations administrators who need it. The chain detects changes
relative to a trusted checkpoint; it cannot restore deleted or rewritten
records by itself.

When using the legacy SQLite deployment (shared URL unset),
administrators can download a consistent snapshot of the audit database from
`GET /autonomy/audit/database/backup`. The endpoint requires an admin bearer
token, opens the SQLite database read-only, uses SQLite's online backup API,
checks the snapshot with `PRAGMA integrity_check`, and streams the file without
retaining a server-side copy. The same admin-only API provides
`GET /autonomy/audit/database/backup/action-plans` and
`GET /autonomy/audit/database/backup/gitops` for the durable action-plan and
GitOps stores. Each store is snapshotted independently; the API does not create
a cross-database transaction. These endpoints are SQLite-specific and are not
a MySQL backup mechanism. The audit-idempotency SQLite store needs its own
protected backup. For shared SQL deployment backups and recovery, follow the
[shared database operations runbook](docs/shared-database-operations.md).

For a legacy SQLite deployment, store backups separately with access
controls and a tested restore window. To recover those local files, stop the
service, preserve the damaged database as evidence, restore the selected backup
to its configured database path, restart, and verify readiness. Export and
independently verify the restored chain, then compare its final hash and event
count with the most recent external checkpoint. If they differ, preserve both
copies and investigate before resuming normal audit operations; do not silently
replace the checkpoint or rewrite the chain. For shared MySQL deployment,
follow the provider-specific restore procedure in the
[shared database operations runbook](docs/shared-database-operations.md).

Before an incident, run a non-destructive restore drill against each downloaded
backup. The tool checks SQLite integrity, loads the store using the application's
own persistence code in an isolated temporary copy, and verifies the audit hash
chain. It never opens the supplied backup for writing:

```powershell
python backend/verify_database_backup.py audit path\to\cloudops-audit-backup.db
python backend/verify_database_backup.py idempotency path\to\cloudops-idempotency-backup.db
python backend/verify_database_backup.py action-plans path\to\cloudops-action-plans-backup.db
python backend/verify_database_backup.py gitops path\to\cloudops-gitops-backup.db
```

A successful drill prints JSON with `status: ok` and the number of records
loaded. A failed integrity, schema, deserialization, or audit-chain check exits
with status 1 and a concise diagnostic. A successful drill validates a backup
copy; it does not replace a production restore rehearsal or verify external
checkpoints and application readiness.

GitOps change sets and their lifecycle state survive process restarts.
With `CLOUDOPS_DATABASE_URL` unset, the default file is
`backend/gitops_changes.db`; set `CLOUDOPS_GITOPS_DB_PATH` to place it
elsewhere. With the shared URL configured, GitOps state is stored in the shared
SQL database alongside audit events, audit idempotency, action plans, and
shared rate-limit counters. `/ready` checks the configured persistence schema.
Corrupt stored change data fails startup rather than silently dropping pending
reviews. Real infrastructure mutation remains disabled.

The console is a small browser client served directly by FastAPI. Shared SQL
persistence is optional and supports MySQL through PyMySQL or SQLite for
processes sharing one local file. See the
[shared database deployment and recovery runbook](docs/shared-database-operations.md)
for migration, import, readiness, backup, and recovery boundaries.
Container deployment and CI are provided. Infrastructure as code and LLM
integration are not currently provided.
