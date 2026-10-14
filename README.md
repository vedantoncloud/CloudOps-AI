# CloudOps AI

CloudOps AI is a cloud operations platform designed to help monitor,
analyze, and manage cloud infrastructure with automation and AI-powered insights.

## Project Status

?? Under active development.

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
gateway to issue, rotate, and revoke them. This initial boundary attaches the
principal and tenant to request state; resource-level tenant isolation and
authenticated-principal audit attribution remain to be completed.

## Planned Stack

- React
- FastAPI
- PostgreSQL
- AWS
- Docker
- GitHub Actions
- Terraform
- Kubernetes
- AI/LLM integration
