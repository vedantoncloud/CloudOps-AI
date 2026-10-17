from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
import re
import sqlite3

from auth import AccessControlMiddleware, require_role
from services.aws_service import AWSService
from autonomy.api import router as autonomy_router
from autonomy.control_loop_api import router as control_loop_router
from autonomy.gitops_api import router as gitops_router
from autonomy.control_plane_api import router as control_plane_router
from autonomy.audit_api import router as audit_router
from autonomy.autonomous_control_plane_api import router as autonomous_control_plane_router
from autonomy.autonomous_run_api import router as autonomous_run_router
from autonomy.persistent_audit_health_api import router as persistent_audit_health_router
from autonomy.persistent_audit_reconciliation_api import router as persistent_audit_reconciliation_router
from autonomy.resource_governance_api import router as resource_governance_router
from autonomy.resource_inventory_api import router as resource_inventory_router
from autonomy.resource_inventory_api import _resource_tenant
from autonomy.audit_api import audit_trail
from autonomy.persistent_audit_reconciliation_api import DEFAULT_DB_PATH


app = FastAPI(
    title="CloudOps AI",
    description="AI-powered Cloud Operations Platform",
    version="0.1.0",
)
app.add_middleware(AccessControlMiddleware)

CONSOLE_PAGE = Path(__file__).parent / "static" / "console.html"


aws_service = AWSService()

app.include_router(autonomy_router)
app.include_router(control_loop_router)
app.include_router(gitops_router)
app.include_router(control_plane_router)
app.include_router(audit_router)
app.include_router(autonomous_control_plane_router)
app.include_router(autonomous_run_router)
app.include_router(persistent_audit_health_router)
app.include_router(persistent_audit_reconciliation_router)
app.include_router(resource_governance_router)
app.include_router(resource_inventory_router)


def _sqlite_store_ready(database_path: str | Path) -> bool:
    """Check that a configured SQLite store can be opened and queried."""
    path = Path(database_path).resolve()
    try:
        with sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1
        ) as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except (OSError, sqlite3.Error, ValueError):
        return False


@app.get("/")
def root():
    return {
        "message": "CloudOps AI is running",
        "version": "0.1.0",
    }


@app.get("/console", include_in_schema=False)
def console():
    """Serve the authenticated operations console."""
    return FileResponse(CONSOLE_PAGE, media_type="text/html")


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "cloudops-ai",
    }


@app.get("/ready")
def readiness_check():
    """Report whether the service can currently reach its AWS dependency.

    Keep /health as a cheap liveness probe; readiness is suitable for routing
    traffic only when the integration used by the API is available.
    """
    try:
        result = aws_service.get_status()
    except Exception:
        result = {"status": "disconnected"}

    aws_ready = result.get("status") == "connected"
    persistence = {
        "audit_events": (
            "healthy" if _sqlite_store_ready(audit_trail.database_path) else "unhealthy"
        ),
        "audit_idempotency": (
            "healthy" if _sqlite_store_ready(DEFAULT_DB_PATH) else "unhealthy"
        ),
    }
    ready = aws_ready and all(status == "healthy" for status in persistence.values())
    payload = {
        "status": "ready" if ready else "not_ready",
        "service": "cloudops-ai",
        "dependencies": {
            "aws": "healthy" if aws_ready else "unhealthy",
            **persistence,
        },
    }
    if not ready:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/cloud/aws/status")
def aws_status(request: Request):
    result = aws_service.get_status()
    if (
        not getattr(request.state, "tenant_scoped", False)
        or getattr(getattr(request.state, "principal", None), "role", None) == "admin"
    ):
        return result

    # The configured AWS identity is shared by the service process today. Do
    # not disclose its account number, principal ARN, or raw AWS error details
    # to tenant users while account-specific credentials are not configured.
    return {
        key: result[key]
        for key in ("provider", "status", "services", "message")
        if key in result
    }


@app.get("/cloud/aws/services/{service_name}")
def aws_service_health(service_name: str, request: Request):
    result = aws_service.get_service_health(service_name)
    if (
        getattr(request.state, "tenant_scoped", False)
        and getattr(getattr(request.state, "principal", None), "role", None) != "admin"
    ):
        # A health check runs with the process-wide AWS identity. Keep raw SDK
        # errors, which can contain account or request details, within admins.
        return {
            key: result[key]
            for key in ("service", "status", "message")
            if key in result
        }
    return result


@app.get("/cloud/aws/account-costs")
def aws_account_costs(request: Request):
    # Cost Explorer reports the shared AWS account, so never expose it to tenant users.
    require_role(request.state.principal, "admin")
    result = aws_service.get_account_costs()
    if result["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail="AWS billing data is unavailable")
    return result


@app.get("/cloud/aws/ec2/summary")
def aws_ec2_summary(request: Request):
    if not getattr(request.state, "tenant_scoped", False):
        return aws_service.get_ec2_summary()
    instances = []
    next_token = None
    seen_tokens = set()
    while True:
        inventory = _tenant_ec2_instances(request, None, None, 1000, next_token)
        if inventory.get("status") != "healthy":
            return inventory
        instances.extend(inventory.get("instances", []))
        next_token = inventory.get("next_token")
        if not next_token:
            break
        if next_token in seen_tokens:
            return {"service": "ec2", "status": "unhealthy"}
        seen_tokens.add(next_token)
    return {
        "service": "ec2",
        "status": "healthy",
        "total_instances": len(instances),
        "running_instances": sum(item.get("state") == "running" for item in instances),
        "stopped_instances": sum(item.get("state") == "stopped" for item in instances),
    }


def _tenant_ec2_instances(request: Request, state: str | None, tag: str | None, max_results=None, next_token=None, name=None):
    if max_results is None and next_token is None:
        result = aws_service.get_ec2_instances(state, tag, name=name) if name else aws_service.get_ec2_instances(state, tag)
    else:
        result = aws_service.get_ec2_instances(state, tag, max_results, next_token, name=name)
    if result.get("status") != "healthy" or not getattr(request.state, "tenant_scoped", False):
        return result
    tenant_id = request.state.tenant_id
    result = dict(result)
    result["instances"] = [
        item for item in result.get("instances", [])
        if _resource_tenant({"tags": item.get("tags", {})}) == tenant_id
    ]
    return result


def _require_tenant_ec2_instance(request: Request, instance_id: str) -> None:
    """Hide EC2 instances that are not explicitly owned by this tenant."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    result = aws_service.get_ec2_instance(instance_id)
    if result.get("status") != "healthy":
        raise HTTPException(status_code=503, detail="EC2 inventory is unavailable")
    tenant_id = request.state.tenant_id
    instance = result.get("instance")
    owned = instance is not None and _resource_tenant({"tags": instance.get("tags", {})}) == tenant_id
    if not owned:
        # Use the same response for absent and foreign-owned resources.
        raise HTTPException(status_code=404, detail="EC2 instance not found")


@app.get("/cloud/aws/ec2/instances")
def aws_ec2_instances(request: Request, state: str = None, tag: str = None, max_results: int = None, next_token: str = None, name: str = None):
    valid_states = {
        "pending",
        "running",
        "shutting-down",
        "terminated",
        "stopping",
        "stopped",
    }

    if state is not None and state not in valid_states:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid EC2 state: {state}",
        )

    if max_results is not None and not 5 <= max_results <= 1000:
        raise HTTPException(status_code=400, detail="max_results must be between 5 and 1000")

    if name is not None and (not name.strip() or len(name) > 128):
        raise HTTPException(status_code=400, detail="name must contain 1 to 128 characters")

    return _tenant_ec2_instances(request, state, tag, max_results, next_token, name.strip() if name else None)


@app.get("/cloud/aws/s3/buckets")
def aws_s3_buckets(
    request: Request,
    max_buckets: int = 1000,
    continuation_token: str = None,
):
    if max_buckets is not None and not 1 <= max_buckets <= 10000:
        raise HTTPException(status_code=400, detail="max_buckets must be between 1 and 10000")
    result = aws_service.get_s3_buckets(max_buckets, continuation_token)
    if result.get("status") != "healthy" or not getattr(request.state, "tenant_scoped", False):
        return result
    result = dict(result)
    result["buckets"] = [
        bucket for bucket in result.get("buckets", [])
        if _tenant_owns_s3_bucket(request, bucket.get("name"))
    ]
    return result


def _tenant_owns_s3_bucket(request: Request, bucket_name: str | None) -> bool:
    if not getattr(request.state, "tenant_scoped", False):
        return True
    if not bucket_name:
        return False
    result = aws_service.get_s3_bucket_tags(bucket_name)
    return (
        result.get("status") == "healthy"
        and _resource_tenant({"tags": result.get("tags", {})}) == request.state.tenant_id
    )


def _require_tenant_s3_bucket(request: Request, bucket_name: str) -> None:
    if not _tenant_owns_s3_bucket(request, bucket_name):
        raise HTTPException(status_code=404, detail="S3 bucket not found")


@app.get("/cloud/aws/s3/buckets/{bucket_name}")
def aws_s3_bucket_details(bucket_name: str, request: Request):
    _require_tenant_s3_bucket(request, bucket_name)
    result = aws_service.get_s3_bucket_details(bucket_name)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/objects")
def aws_s3_objects(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = 1000,
    continuation_token: str = None,
    delimiter: str = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_objects(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
        continuation_token=continuation_token,
        delimiter=delimiter,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/objects/metadata")
def aws_s3_object_metadata(bucket_name: str, request: Request, key: str):
    """Inspect one S3 object while enforcing the bucket's tenant boundary."""
    _require_tenant_s3_bucket(request, bucket_name)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    result = aws_service.get_s3_object_metadata(bucket_name, key)
    if result["status"] == "unhealthy":
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/objects/download")
def aws_s3_object_download_url(bucket_name: str, request: Request, key: str):
    """Issue a five-minute download URL after checking bucket tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    result = aws_service.create_s3_object_download_url(bucket_name, key)
    if result["status"] == "unhealthy":
        raise HTTPException(status_code=403, detail=result["error"])
    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/statistics")
def aws_s3_object_statistics(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_object_statistics(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/largest-objects")
def aws_s3_largest_objects(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = None,
    top_n: int = 5,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    if top_n <= 0 or top_n > 100:
        raise HTTPException(
            status_code=400,
            detail="top_n must be between 1 and 100",
        )

    result = aws_service.get_s3_largest_objects(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
        top_n=top_n,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/health")
def aws_s3_bucket_health(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_bucket_health(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/insights")
def aws_s3_bucket_insights(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_bucket_insights(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/optimization")
def aws_s3_bucket_optimization(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    max_keys: int = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_bucket_optimization(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/insights")
def aws_ec2_insights(instance_id: str, request: Request):
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid EC2 instance ID",
        )

    _require_tenant_ec2_instance(request, instance_id)
    result = aws_service.get_ec2_insights(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}")
def aws_ec2_instance_details(instance_id: str, request: Request):
    """Return one EC2 inventory record, applying the same tenant scope as lists."""
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID")

    result = aws_service.get_ec2_instance(instance_id)
    if result.get("status") != "healthy":
        raise HTTPException(status_code=503, detail="EC2 inventory is unavailable")

    instance = result.get("instance")
    if instance is None or (
        getattr(request.state, "tenant_scoped", False)
        and _resource_tenant({"tags": instance.get("tags", {})}) != request.state.tenant_id
    ):
        raise HTTPException(status_code=404, detail="EC2 instance not found")

    return {"service": "ec2", "status": "healthy", "instance": instance}


@app.get("/cloud/aws/ec2/efficiency-insights")
def aws_ec2_efficiency_insights(request: Request):
    if getattr(request.state, "tenant_scoped", False):
        inventory = _tenant_ec2_instances(request, None, None)
        if inventory.get("status") != "healthy":
            return inventory
        result = aws_service.get_ec2_efficiency_insights(instances=inventory.get("instances", []))
    else:
        result = aws_service.get_ec2_efficiency_insights()

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/cost-insights")
def aws_ec2_cost_insights(request: Request):
    if getattr(request.state, "tenant_scoped", False):
        inventory = _tenant_ec2_instances(request, None, None)
        if inventory.get("status") != "healthy":
            return inventory
        result = aws_service.get_ec2_cost_insights(instances=inventory.get("instances", []))
    else:
        result = aws_service.get_ec2_cost_insights()

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/rightsizing-insights")
def aws_ec2_rightsizing_insights(request: Request):
    if getattr(request.state, "tenant_scoped", False):
        inventory = _tenant_ec2_instances(request, None, None)
        if inventory.get("status") != "healthy":
            return inventory
        result = aws_service.get_ec2_rightsizing_insights(instances=inventory.get("instances", []))
    else:
        result = aws_service.get_ec2_rightsizing_insights()

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/security-insights")
def aws_ec2_security_insights(request: Request):
    if getattr(request.state, "tenant_scoped", False):
        inventory = _tenant_ec2_instances(request, None, None)
        if inventory.get("status") != "healthy":
            return inventory
        result = aws_service.get_ec2_security_insights(instances=inventory.get("instances", []))
    else:
        result = aws_service.get_ec2_security_insights()

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/cpu")
def aws_ec2_cpu(instance_id: str, request: Request):
    _require_tenant_ec2_instance(request, instance_id)
    result = aws_service.get_ec2_cpu_utilization(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/network")
def aws_ec2_network_utilization(instance_id: str, request: Request):
    _require_tenant_ec2_instance(request, instance_id)
    result = aws_service.get_ec2_network_utilization(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/security-insights")
def aws_s3_bucket_security_insights(bucket_name: str, request: Request):
    _require_tenant_s3_bucket(request, bucket_name)
    result = aws_service.get_s3_security_insights(bucket_name)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}/cost-insights")
def aws_s3_bucket_cost_insights(
    bucket_name: str,
    request: Request,
    prefix: str | None = None,
    max_keys: int | None = None,
):
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys is not None and not 1 <= max_keys <= 1000:
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_cost_insights(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    )

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/status")
def aws_ec2_instance_status(instance_id: str, request: Request):
    _require_tenant_ec2_instance(request, instance_id)
    result = aws_service.get_ec2_instance_status(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/metrics")
def aws_ec2_metrics(instance_id: str, request: Request, lookback_hours: int = 1):
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid EC2 instance ID",
        )

    _require_tenant_ec2_instance(request, instance_id)
    if not 1 <= lookback_hours <= 24:
        raise HTTPException(status_code=400, detail="lookback_hours must be between 1 and 24")
    result = aws_service.get_ec2_metrics(instance_id, lookback_hours=lookback_hours)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


