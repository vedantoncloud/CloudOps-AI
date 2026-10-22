from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pathlib import Path
import re
import sqlite3

from auth import AccessControlMiddleware, require_role
from observability import RequestObservabilityMiddleware, aws_operation_metrics, database_operation_metrics, request_metrics
from rate_limit import RateLimitMiddleware
from request_limits import RequestSizeLimitMiddleware, ResponseSizeLimitMiddleware
from services.aws_service import AWSService
from autonomy.api import router as autonomy_router
from autonomy.api import action_plan_store
from autonomy.control_loop_api import router as control_loop_router
from autonomy.gitops_api import router as gitops_router
from autonomy.gitops_api import registry as gitops_registry
from autonomy.control_plane_api import router as control_plane_router
from autonomy.audit_api import router as audit_router
from autonomy.autonomous_control_plane_api import router as autonomous_control_plane_router
from autonomy.autonomous_run_api import router as autonomous_run_router
from autonomy.lifecycle_api import router as lifecycle_router
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
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(ResponseSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AccessControlMiddleware)
app.add_middleware(RequestObservabilityMiddleware)

CONSOLE_PAGE = Path(__file__).parent / "static" / "console.html"


aws_service = AWSService()

app.include_router(autonomy_router)
app.include_router(control_loop_router)
app.include_router(gitops_router)
app.include_router(control_plane_router)
app.include_router(audit_router)
app.include_router(autonomous_control_plane_router)
app.include_router(autonomous_run_router)
app.include_router(lifecycle_router)
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


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Expose bounded-cardinality HTTP counters and latency histograms."""
    return PlainTextResponse(
        request_metrics.prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/operations/failures")
def operation_failures(request: Request):
    """Summarize server-side request failures without exposing error payloads."""
    require_role(request.state.principal, "admin")
    return request_metrics.failure_snapshot()


@app.get("/operations/aws-failures")
def aws_operation_failures(request: Request):
    """Summarize AWS operation failures without exposing provider errors."""
    require_role(request.state.principal, "admin")
    return aws_operation_metrics.failure_snapshot()


@app.get("/operations/database-failures")
def database_operation_failures(request: Request):
    """Summarize audit-store operation outcomes without storage details."""
    require_role(request.state.principal, "admin")
    return database_operation_metrics.failure_snapshot()


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
        "action_plans": (
            "healthy" if _sqlite_store_ready(action_plan_store.database_path) else "unhealthy"
        ),
        "gitops_changes": (
            "healthy"
            if gitops_registry.database_path is None
            or _sqlite_store_ready(gitops_registry.database_path)
            else "unhealthy"
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
def aws_account_costs(request: Request, days: int = 30):
    # Cost Explorer reports the shared AWS account, so never expose it to tenant users.
    require_role(request.state.principal, "admin")
    if not 7 <= days <= 90:
        raise HTTPException(status_code=400, detail="days must be between 7 and 90")
    try:
        result = aws_service.get_account_costs(days=days)
    except Exception:
        raise HTTPException(status_code=503, detail="AWS billing data is unavailable")
    if not isinstance(result, dict) or result.get("status") != "healthy":
        raise HTTPException(status_code=503, detail="AWS billing data is unavailable")
    return result


@app.get("/cloud/aws/ec2/summary")
def aws_ec2_summary(request: Request):
    if not getattr(request.state, "tenant_scoped", False):
        result = aws_service.get_ec2_summary()
        if result.get("status") != "healthy":
            _raise_aws_resource_unavailable()
        return result
    inventory = _all_tenant_ec2_instances(request)
    instances = inventory["instances"]
    return {
        "service": "ec2",
        "status": "healthy",
        "total_instances": len(instances),
        "running_instances": sum(item.get("state") == "running" for item in instances),
        "stopped_instances": sum(item.get("state") == "stopped" for item in instances),
    }


@app.get("/cloud/aws/ec2/regions")
def aws_ec2_regions():
    result = aws_service.get_ec2_regions()
    if result.get("status") != "healthy":
        _raise_aws_resource_unavailable()
    return result


def _all_tenant_ec2_instances(request: Request, region: str | None = None):
    """Load every EC2 page in a region and apply tenant ownership before aggregation."""
    instances = []
    next_token = None
    seen_tokens = set()
    while True:
        inventory = _tenant_ec2_instances(request, None, None, 1000, next_token, region=region)
        if inventory.get("status") != "healthy":
            _raise_aws_resource_unavailable()
        instances.extend(inventory.get("instances", []))
        next_token = inventory.get("next_token")
        if not next_token:
            break
        if next_token in seen_tokens:
            _raise_aws_resource_unavailable()
        seen_tokens.add(next_token)
    return {"service": "ec2", "status": "healthy", "instances": instances}


def _tenant_ec2_instances(request: Request, state: str | None, tag: str | None, max_results=None, next_token=None, name=None, region=None, instance_type=None, vpc_id=None, subnet_id=None, availability_zone=None):
    filters = {}
    if name or max_results is not None or next_token is not None:
        filters["name"] = name
    if region:
        filters["region"] = region
    if instance_type:
        filters["instance_type"] = instance_type
    if vpc_id:
        filters["vpc_id"] = vpc_id
    if subnet_id:
        filters["subnet_id"] = subnet_id
    if availability_zone:
        filters["availability_zone"] = availability_zone
    if max_results is None and next_token is None:
        result = aws_service.get_ec2_instances(state, tag, **filters)
    else:
        result = aws_service.get_ec2_instances(state, tag, max_results, next_token, **filters)
    if result.get("status") != "healthy" or not getattr(request.state, "tenant_scoped", False):
        return result
    tenant_id = request.state.tenant_id
    result = dict(result)
    result["instances"] = [
        item for item in result.get("instances", [])
        if _resource_tenant({"tags": item.get("tags", {})}) == tenant_id
    ]
    return result


def _require_tenant_ec2_instance(request: Request, instance_id: str, region: str | None = None) -> None:
    """Hide EC2 instances that are not explicitly owned by this tenant."""
    if not getattr(request.state, "tenant_scoped", False):
        return
    result = _aws_resource_result(
        lambda: aws_service.get_ec2_instance(
            instance_id, **({"region": region} if region else {})
        )
    )
    tenant_id = request.state.tenant_id
    instance = result.get("instance")
    owned = instance is not None and _resource_tenant({"tags": instance.get("tags", {})}) == tenant_id
    if not owned:
        # Use the same response for absent and foreign-owned resources.
        raise HTTPException(status_code=404, detail="EC2 instance not found")


def _validate_ec2_instance_id(instance_id: str) -> None:
    """Reject malformed identifiers before making provider calls."""
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID")


def _validate_ec2_region(region: str | None) -> None:
    if region is not None and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9]", region):
        raise HTTPException(status_code=400, detail="Invalid AWS region")


def _raise_aws_resource_unavailable() -> None:
    """Raise a stable dependency error without leaking provider diagnostics."""
    raise HTTPException(status_code=503, detail="AWS resource data is unavailable")


def _aws_resource_result(operation):
    """Map provider exceptions and unhealthy results to a stable dependency error."""
    try:
        result = operation()
    except Exception:
        _raise_aws_resource_unavailable()
    if not isinstance(result, dict) or result.get("status") != "healthy":
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/ec2/instances")
def aws_ec2_instances(request: Request, state: str = None, tag: str = None, max_results: int = None, next_token: str = None, name: str = None, region: str = None, instance_type: str = None, vpc_id: str = None, subnet_id: str = None, availability_zone: str = None):
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

    if instance_type is not None and (
        not re.fullmatch(r"[a-z][a-z0-9-]*\.[a-z0-9-]+", instance_type, re.IGNORECASE)
        or len(instance_type) > 64
    ):
        raise HTTPException(status_code=400, detail="instance_type must be a valid EC2 instance type")

    if vpc_id is not None and not re.fullmatch(r"vpc-[0-9a-fA-F]{8,17}", vpc_id):
        raise HTTPException(status_code=400, detail="vpc_id must be a valid VPC ID")
    if subnet_id is not None and not re.fullmatch(r"subnet-[0-9a-fA-F]{8,17}", subnet_id):
        raise HTTPException(status_code=400, detail="subnet_id must be a valid subnet ID")
    if availability_zone is not None and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9][a-z]", availability_zone):
        raise HTTPException(status_code=400, detail="availability_zone must be a valid AWS availability zone")

    _validate_ec2_region(region)

    result = _tenant_ec2_instances(
        request, state, tag, max_results, next_token,
        name.strip() if name else None, region, instance_type, vpc_id, subnet_id, availability_zone,
    )
    if result.get("status") != "healthy":
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/s3/buckets")
def aws_s3_buckets(
    request: Request,
    max_buckets: int = 1000,
    continuation_token: str = None,
    prefix: str = None,
):
    if max_buckets is not None and not 1 <= max_buckets <= 10000:
        raise HTTPException(status_code=400, detail="max_buckets must be between 1 and 10000")
    if prefix is not None and (not prefix.strip() or len(prefix) > 255):
        raise HTTPException(status_code=400, detail="prefix must contain 1 to 255 characters")
    def list_page(page_size, cursor):
        try:
            result = aws_service.get_s3_buckets(
                page_size, cursor,
                **({"prefix": prefix} if prefix is not None else {}),
            )
        except Exception:
            raise HTTPException(
                status_code=503, detail="AWS resource data is unavailable"
            ) from None
        return result

    result = list_page(max_buckets, continuation_token)
    if (not isinstance(result, dict) or result.get("status") != "healthy"
            or not isinstance(result.get("buckets"), list)
            or any(not isinstance(bucket, dict) for bucket in result["buckets"])):
        _raise_aws_resource_unavailable()
    if not getattr(request.state, "tenant_scoped", False):
        return result
    result = dict(result)
    visible_buckets = []
    cursor = continuation_token
    seen_cursors = {cursor} if cursor else set()
    # Fill a tenant-visible page across a bounded number of AWS pages. The
    # continuation cursor always points to the next unexamined AWS page.
    for _ in range(10):
        visible_buckets.extend(
            bucket for bucket in result.get("buckets", [])
            if _tenant_owns_s3_bucket(request, bucket.get("name"))
        )
        if len(visible_buckets) >= max_buckets or not result.get("is_truncated"):
            break
        cursor = result.get("next_continuation_token")
        if not cursor or cursor in seen_cursors:
            raise HTTPException(status_code=503, detail="S3 inventory pagination is unavailable")
        seen_cursors.add(cursor)
        result = list_page(max_buckets - len(visible_buckets), cursor)
        if (not isinstance(result, dict) or result.get("status") != "healthy"
                or not isinstance(result.get("buckets"), list)
                or any(not isinstance(bucket, dict) for bucket in result["buckets"])):
            raise HTTPException(status_code=503, detail="S3 inventory is unavailable")
    result["buckets"] = visible_buckets
    return result


def _tenant_owns_s3_bucket(request: Request, bucket_name: str | None) -> bool:
    if not getattr(request.state, "tenant_scoped", False):
        return True
    if not bucket_name:
        return False
    try:
        result = aws_service.get_s3_bucket_tags(bucket_name)
    except Exception:
        raise HTTPException(
            status_code=503, detail="S3 ownership verification is unavailable"
        ) from None
    if (not isinstance(result, dict)
            or result.get("status") not in {"healthy", "unhealthy", "missing"}
            or (result.get("status") == "healthy"
                and not isinstance(result.get("tags", {}), dict))):
        raise HTTPException(status_code=503, detail="S3 ownership verification is unavailable")
    if result.get("status") == "unhealthy":
        # A failed ownership check is not evidence that the bucket is foreign.
        # Fail the request so operators can distinguish outages from an empty scope.
        raise HTTPException(status_code=503, detail="S3 ownership verification is unavailable")
    if result.get("status") == "missing":
        return False
    return result.get("status") == "healthy" and _resource_tenant(
        {"tags": result.get("tags", {})}
    ) == request.state.tenant_id


def _require_tenant_s3_bucket(request: Request, bucket_name: str) -> None:
    if not _tenant_owns_s3_bucket(request, bucket_name):
        raise HTTPException(status_code=404, detail="S3 bucket not found")


@app.get("/cloud/aws/s3/buckets/{bucket_name}")
def aws_s3_bucket_details(bucket_name: str, request: Request):
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_details(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/versioning")
def aws_s3_bucket_versioning(bucket_name: str, request: Request):
    """Return bucket versioning state after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_versioning(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/lifecycle")
def aws_s3_bucket_lifecycle(bucket_name: str, request: Request):
    """Inspect lifecycle rules after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_lifecycle(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/replication")
def aws_s3_bucket_replication(bucket_name: str, request: Request):
    """Inspect replication rules after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_replication(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/logging")
def aws_s3_bucket_logging(bucket_name: str, request: Request):
    """Inspect server access logging after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_logging(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/encryption")
def aws_s3_bucket_encryption(bucket_name: str, request: Request):
    """Inspect default bucket encryption after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_encryption(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/tags")
def aws_s3_bucket_tags(bucket_name: str, request: Request):
    """Review bucket metadata after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_tags(bucket_name))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/policy")
def aws_s3_bucket_policy(bucket_name: str, request: Request):
    """Review a bucket policy after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_bucket_policy(bucket_name))


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

    return _aws_resource_result(lambda: aws_service.get_s3_objects(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
        continuation_token=continuation_token,
        delimiter=delimiter,
    ))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/objects/metadata")
def aws_s3_object_metadata(
    bucket_name: str, request: Request, key: str, version_id: str = None
):
    """Inspect one S3 object while enforcing the bucket's tenant boundary."""
    _require_tenant_s3_bucket(request, bucket_name)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    if version_id is not None and not version_id:
        raise HTTPException(status_code=400, detail="version_id must not be empty")
    return _aws_resource_result(lambda: (
        aws_service.get_s3_object_metadata(bucket_name, key)
        if version_id is None
        else aws_service.get_s3_object_metadata(bucket_name, key, version_id)
    ))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/object-versions")
def aws_s3_object_versions(
    bucket_name: str,
    request: Request,
    prefix: str = None,
    key_marker: str = None,
    version_id_marker: str = None,
    max_keys: int = 100,
):
    """Browse one bounded page of S3 object versions within the tenant bucket."""
    _require_tenant_s3_bucket(request, bucket_name)
    if max_keys <= 0 or max_keys > 1000:
        raise HTTPException(status_code=400, detail="max_keys must be between 1 and 1000")
    return _aws_resource_result(lambda: aws_service.get_s3_object_versions(
        bucket_name, prefix=prefix, key_marker=key_marker,
        version_id_marker=version_id_marker, max_keys=max_keys,
    ))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/objects/download")
def aws_s3_object_download_url(
    bucket_name: str, request: Request, key: str, version_id: str = None
):
    """Issue a five-minute download URL after checking bucket tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    if not key:
        raise HTTPException(status_code=400, detail="key must not be empty")
    if version_id == "":
        raise HTTPException(status_code=400, detail="version_id must not be empty")
    return _aws_resource_result(lambda: (
        aws_service.create_s3_object_download_url(bucket_name, key, version_id)
        if version_id is not None
        else aws_service.create_s3_object_download_url(bucket_name, key)
    ))


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

    return _aws_resource_result(lambda: aws_service.get_s3_object_statistics(
        bucket_name, prefix=prefix, max_keys=max_keys,
    ))


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

    return _aws_resource_result(lambda: aws_service.get_s3_largest_objects(
        bucket_name, prefix=prefix, max_keys=max_keys, top_n=top_n,
    ))


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

    return _aws_resource_result(lambda: aws_service.get_s3_bucket_health(
        bucket_name, prefix=prefix, max_keys=max_keys,
    ))


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

    return _aws_resource_result(lambda: aws_service.get_s3_bucket_insights(
        bucket_name, prefix=prefix, max_keys=max_keys,
    ))


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

    return _aws_resource_result(lambda: aws_service.get_s3_bucket_optimization(
        bucket_name, prefix=prefix, max_keys=max_keys,
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}/insights")
def aws_ec2_insights(instance_id: str, request: Request, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_insights(
        instance_id, **({"region": region} if region else {})
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}")
def aws_ec2_instance_details(instance_id: str, request: Request, region: str | None = None):
    """Return one EC2 inventory record, applying the same tenant scope as lists."""
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)

    result = _aws_resource_result(lambda: aws_service.get_ec2_instance(
        instance_id, **({"region": region} if region else {})
    ))

    instance = result.get("instance")
    if instance is None or (
        getattr(request.state, "tenant_scoped", False)
        and _resource_tenant({"tags": instance.get("tags", {})}) != request.state.tenant_id
    ):
        raise HTTPException(status_code=404, detail="EC2 instance not found")

    return {"service": "ec2", "status": "healthy", "instance": instance}


@app.get("/cloud/aws/ec2/efficiency-insights")
def aws_ec2_efficiency_insights(request: Request, region: str | None = None):
    _validate_ec2_region(region)
    if not getattr(request.state, "tenant_scoped", False) and not region:
        operation = lambda: aws_service.get_ec2_efficiency_insights()
    else:
        inventory = _all_tenant_ec2_instances(request, region)
        if inventory.get("status") != "healthy":
            return inventory
        operation = lambda: aws_service.get_ec2_efficiency_insights(instances=inventory.get("instances", []), **({"region": region} if region else {}))

    return _aws_resource_result(operation)


@app.get("/cloud/aws/ec2/cost-insights")
def aws_ec2_cost_insights(request: Request, region: str | None = None):
    _validate_ec2_region(region)
    if not getattr(request.state, "tenant_scoped", False) and not region:
        operation = lambda: aws_service.get_ec2_cost_insights()
    else:
        inventory = _all_tenant_ec2_instances(request, region)
        if inventory.get("status") != "healthy":
            return inventory
        operation = lambda: aws_service.get_ec2_cost_insights(instances=inventory.get("instances", []), **({"region": region} if region else {}))

    return _aws_resource_result(operation)


@app.get("/cloud/aws/ec2/rightsizing-insights")
def aws_ec2_rightsizing_insights(request: Request, region: str | None = None):
    _validate_ec2_region(region)
    if not getattr(request.state, "tenant_scoped", False) and not region:
        operation = lambda: aws_service.get_ec2_rightsizing_insights()
    else:
        inventory = _all_tenant_ec2_instances(request, region)
        if inventory.get("status") != "healthy":
            return inventory
        operation = lambda: aws_service.get_ec2_rightsizing_insights(instances=inventory.get("instances", []), **({"region": region} if region else {}))

    return _aws_resource_result(operation)


@app.get("/cloud/aws/ec2/security-insights")
def aws_ec2_security_insights(request: Request, region: str | None = None):
    _validate_ec2_region(region)
    if not getattr(request.state, "tenant_scoped", False) and not region:
        operation = lambda: aws_service.get_ec2_security_insights()
    else:
        inventory = _all_tenant_ec2_instances(request, region)
        if inventory.get("status") != "healthy":
            return inventory
        operation = lambda: aws_service.get_ec2_security_insights(instances=inventory.get("instances", []), **({"region": region} if region else {}))

    return _aws_resource_result(operation)


@app.get("/cloud/aws/ec2/instances/{instance_id}/cpu")
def aws_ec2_cpu(instance_id: str, request: Request, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_cpu_utilization(
        instance_id, **({"region": region} if region else {})
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}/network")
def aws_ec2_network_utilization(instance_id: str, request: Request, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_network_utilization(
        instance_id, **({"region": region} if region else {})
    ))


@app.get("/cloud/aws/s3/buckets/{bucket_name}/security-insights")
def aws_s3_bucket_security_insights(bucket_name: str, request: Request):
    _require_tenant_s3_bucket(request, bucket_name)
    return _aws_resource_result(lambda: aws_service.get_s3_security_insights(bucket_name))


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

    return _aws_resource_result(lambda: aws_service.get_s3_cost_insights(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}/status")
def aws_ec2_instance_status(instance_id: str, request: Request, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_instance_status(
        instance_id, **({"region": region} if region else {})
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}/volumes")
def aws_ec2_instance_volumes(instance_id: str, request: Request, region: str | None = None):
    """Inspect attached EBS encryption only after verifying instance ownership."""
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_instance_volumes(
        instance_id, **({"region": region} if region else {})
    ))


@app.get("/cloud/aws/ec2/instances/{instance_id}/alarms")
def aws_ec2_alarms(
    instance_id: str,
    request: Request,
    next_token: str | None = None,
    region: str | None = None,
):
    """List CloudWatch CPU alarms attached to one visible EC2 instance."""
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    return _aws_resource_result(lambda: aws_service.get_ec2_alarms(
        instance_id,
        next_token=next_token,
        **({"region": region} if region else {}),
    ))


@app.get("/cloud/aws/ec2/alarms")
def aws_ec2_fleet_alarms(request: Request, region: str | None = None):
    """List regional EC2 CPU alarms, scoped to the authenticated tenant."""
    _validate_ec2_region(region)
    result = _aws_resource_result(lambda: aws_service.get_ec2_fleet_alarms(
        **({"region": region} if region else {})
    ))
    if getattr(request.state, "tenant_scoped", False):
        inventory = _all_tenant_ec2_instances(request, region)
        owned_ids = {item.get("instance_id") for item in inventory["instances"]}
        result["alarms"] = [
            alarm for alarm in result.get("alarms", [])
            if set(alarm.get("instance_ids", [])) & owned_ids
        ]
    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/metrics")
def aws_ec2_metrics(instance_id: str, request: Request, lookback_hours: int = 1, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    if not 1 <= lookback_hours <= 24:
        raise HTTPException(status_code=400, detail="lookback_hours must be between 1 and 24")
    return _aws_resource_result(lambda: aws_service.get_ec2_metrics(
        instance_id, lookback_hours=lookback_hours,
        **({"region": region} if region else {}),
    ))


