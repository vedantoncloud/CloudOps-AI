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
