"""Small bearer-token boundary for the assembled API application.

Tokens are supplied by the deployment environment; this module does not issue
or persist credentials. Use an upstream identity provider for token lifecycle.
"""

import json
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from services.aws_service import reset_aws_tenant, set_aws_tenant


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    tenant_id: str


ROLE_LEVEL = {"reader": 1, "operator": 2, "admin": 3}
PUBLIC_PATHS = {"/", "/health", "/ready"}
# These endpoints expose operational details about shared audit storage and
# reconciliation state, so they require an administrator even though they are
# read-only. Approval decisions remain operator-level POST operations.
ADMIN_ONLY_PATHS = {
    "/cloud/aws/account-costs",
    "/operations/failures",
    "/operations/aws-failures",
    "/operations/database-failures",
    "/autonomy/audit/health",
    "/autonomy/audit/pending",
    "/autonomy/audit/reconciliation",
    "/autonomy/audit/integrity",
    # This summary includes shared GitOps counts and audit-event details.
    "/autonomy/control-plane/summary",
}


def load_token_registry(raw: str | None = None) -> dict[str, Principal]:
    """Parse CLOUDOPS_API_TOKENS as {token: {subject, role, tenant_id}}."""
    raw = os.getenv("CLOUDOPS_API_TOKENS") if raw is None else raw
    if not raw:
        return {}
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CLOUDOPS_API_TOKENS must be a JSON object") from exc
    if not isinstance(values, dict):
        raise RuntimeError("CLOUDOPS_API_TOKENS must be a JSON object")
    registry: dict[str, Principal] = {}
    for token, claims in values.items():
        if not isinstance(token, str) or not token or not isinstance(claims, dict):
            raise RuntimeError("Each API token must map to a claims object")
        subject, role, tenant_id = (claims.get(key) for key in ("subject", "role", "tenant_id"))
        if not all(isinstance(value, str) and value.strip() for value in (subject, role, tenant_id)):
            raise RuntimeError("API token claims require subject, role, and tenant_id")
        if role not in ROLE_LEVEL:
            raise RuntimeError(f"Unsupported API token role: {role}")
        registry[token] = Principal(subject.strip(), role, tenant_id.strip())
    return registry


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        mode: str | None = None,
        tokens: dict[str, Principal] | None = None,
        environment: str | None = None,
    ):
        super().__init__(app)
        self.mode = (mode or os.getenv("CLOUDOPS_AUTH_MODE", "development")).lower()
        if self.mode not in {"development", "token"}:
            raise RuntimeError("CLOUDOPS_AUTH_MODE must be 'development' or 'token'")
        self.environment = (environment or os.getenv("CLOUDOPS_ENV", "development")).lower()
        if self.environment not in {"development", "staging", "production"}:
            raise RuntimeError("CLOUDOPS_ENV must be 'development', 'staging', or 'production'")
        if self.environment == "production" and self.mode != "token":
            raise RuntimeError("CLOUDOPS_AUTH_MODE=token is required when CLOUDOPS_ENV=production")
        self.tokens = load_token_registry() if tokens is None else tokens
        if self.mode == "token" and not self.tokens:
            raise RuntimeError("CLOUDOPS_API_TOKENS is required when CLOUDOPS_AUTH_MODE=token")

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        if self.mode == "development":
            request.state.principal = Principal("local-development", "admin", "local")
            request.state.tenant_id = "local"
            request.state.tenant_scoped = False
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        principal = self.tokens.get(token) if scheme.lower() == "bearer" else None
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": "Bearer token required"}, headers={"WWW-Authenticate": "Bearer"})

        required_role = (
            "admin"
            if request.url.path in ADMIN_ONLY_PATHS
            else "reader" if request.method in {"GET", "HEAD"} else "operator"
        )
        if ROLE_LEVEL[principal.role] < ROLE_LEVEL[required_role]:
            return JSONResponse(status_code=403, content={"detail": "Insufficient role"})

        requested_tenant = request.headers.get("x-cloud-tenant")
        if requested_tenant is not None and requested_tenant != principal.tenant_id:
            return JSONResponse(status_code=403, content={"detail": "Tenant access denied"})

        request.state.principal = principal
        request.state.tenant_id = principal.tenant_id
        request.state.tenant_scoped = True
        tenant_token = set_aws_tenant(principal.tenant_id)
        try:
            return await call_next(request)
        finally:
            reset_aws_tenant(tenant_token)


def require_role(principal: Principal, role: str) -> None:
    """Reusable guard for endpoints that need a role above the method default."""
    if role not in ROLE_LEVEL or ROLE_LEVEL.get(principal.role, 0) < ROLE_LEVEL[role]:
        raise HTTPException(status_code=403, detail="Insufficient role")
