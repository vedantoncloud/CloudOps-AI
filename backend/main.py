from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pathlib import Path
from datetime import date, datetime
from math import isfinite
import re
import sqlite3
from urllib.parse import urlsplit

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

    # Readiness depends on a valid provider status contract. Treat malformed
    # provider payloads as an unavailable dependency rather than letting the
    # probe itself fail while reading arbitrary provider data.
    aws_ready = isinstance(result, dict) and result.get("status") == "connected"
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
    try:
        result = aws_service.get_status()
    except Exception:
        raise HTTPException(status_code=503, detail="AWS status is unavailable")
    if (
        not isinstance(result, dict)
        or result.get("provider") != "AWS"
        or result.get("status") not in {"connected", "disconnected"}
        or not isinstance(result.get("message"), str)
        or (result.get("status") == "connected" and not isinstance(result.get("services"), dict))
    ):
        raise HTTPException(status_code=503, detail="AWS status is unavailable")
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
    try:
        result = aws_service.get_service_health(service_name)
    except Exception:
        raise HTTPException(status_code=503, detail="AWS service health is unavailable")
    if (
        not isinstance(result, dict)
        or result.get("service") != service_name
        or result.get("status") not in {"healthy", "unhealthy"}
    ):
        raise HTTPException(status_code=503, detail="AWS service health is unavailable")
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
    def finite_number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

    def valid_period(value):
        if not isinstance(value, dict) or set(value) != {"start", "end_exclusive"}:
            return False
        try:
            return all(
                isinstance(value[key], str)
                and date.fromisoformat(value[key]).isoformat() == value[key]
                for key in ("start", "end_exclusive")
            ) and value["start"] < value["end_exclusive"]
        except (TypeError, ValueError):
            return False

    def valid_daily_row(row):
        if not isinstance(row, dict) or not isinstance(row.get("date"), str) or not finite_number(row.get("amount")):
            return False
        try:
            return date.fromisoformat(row["date"]).isoformat() == row["date"]
        except ValueError:
            return False

    valid_daily = isinstance(result, dict) and isinstance(result.get("daily"), list) and all(
        valid_daily_row(row) for row in result["daily"]
    )
    valid_services = isinstance(result, dict) and isinstance(result.get("services"), list) and all(
        isinstance(row, dict)
        and isinstance(row.get("service"), str)
        and finite_number(row.get("amount"))
        for row in result["services"]
    )
    if (
        not isinstance(result, dict)
        or result.get("service") != "aws-cost-explorer"
        or result.get("status") != "healthy"
        or result.get("days") != days
        or not valid_period(result.get("period"))
        or not valid_period(result.get("comparison_period"))
        or not (result.get("currency") is None or isinstance(result.get("currency"), str))
        or not all(finite_number(result.get(field)) for field in ("total", "previous_total", "change"))
        or not (result.get("change_percent") is None or finite_number(result.get("change_percent")))
        or not valid_daily
        or not valid_services
    ):
        raise HTTPException(status_code=503, detail="AWS billing data is unavailable")
    return result


@app.get("/cloud/aws/ec2/summary")
def aws_ec2_summary(request: Request, region: str | None = None):
    _validate_ec2_region(region)
    if not getattr(request.state, "tenant_scoped", False):
        result = _aws_resource_result(
            lambda: aws_service.get_ec2_summary(**({"region": region} if region else {}))
        )
        count_fields = ("total_instances", "running_instances", "stopped_instances")
        if (
            result.get("service") != "ec2"
            or any(
                not isinstance(result.get(field), int)
                or isinstance(result.get(field), bool)
                or result[field] < 0
                for field in count_fields
            )
            or result["running_instances"] + result["stopped_instances"] > result["total_instances"]
        ):
            _raise_aws_resource_unavailable()
        if region:
            result = {**result, "region": region}
        return result
    inventory = _all_tenant_ec2_instances(request, region)
    instances = inventory["instances"]
    return {
        "service": "ec2",
        "status": "healthy",
        "total_instances": len(instances),
        "running_instances": sum(item.get("state") == "running" for item in instances),
        "stopped_instances": sum(item.get("state") == "stopped" for item in instances),
        **({"region": region} if region else {}),
    }


@app.get("/cloud/aws/ec2/regions")
def aws_ec2_regions():
    result = _aws_resource_result(aws_service.get_ec2_regions)
    regions = result.get("regions")
    if not isinstance(regions, list) or any(
        not isinstance(region, str) or not region.strip() for region in regions
    ):
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
        result = _aws_resource_result(lambda: aws_service.get_ec2_instances(state, tag, **filters))
    else:
        result = _aws_resource_result(
            lambda: aws_service.get_ec2_instances(state, tag, max_results, next_token, **filters)
        )
    instances = result.get("instances")
    if (
        not isinstance(instances, list)
        or any(not isinstance(instance, dict) for instance in instances)
    ):
        _raise_aws_resource_unavailable()
    if not getattr(request.state, "tenant_scoped", False):
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
    _validate_ec2_instance_result(instance, instance_id)
    owned = instance is not None and _resource_tenant({"tags": instance.get("tags", {})}) == tenant_id
    if not owned:
        # Use the same response for absent and foreign-owned resources.
        raise HTTPException(status_code=404, detail="EC2 instance not found")


def _validate_ec2_instance_id(instance_id: str) -> None:
    """Reject malformed identifiers before making provider calls."""
    if not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id):
        raise HTTPException(status_code=400, detail="Invalid EC2 instance ID")


def _validate_ec2_instance_result(instance, requested_instance_id: str) -> None:
    """Reject malformed instance details before returning or using ownership metadata."""
    if instance is None:
        return
    if (
        not isinstance(instance, dict)
        or instance.get("instance_id") != requested_instance_id
        or ("tags" in instance and not isinstance(instance["tags"], dict))
    ):
        _raise_aws_resource_unavailable()


def _validate_ec2_region(region: str | None) -> None:
    if region is not None and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-[0-9]", region):
        raise HTTPException(status_code=400, detail="Invalid AWS region")


def _raise_aws_resource_unavailable() -> None:
    """Raise a stable dependency error without leaking provider diagnostics."""
    raise HTTPException(status_code=503, detail="AWS resource data is unavailable")


def _valid_metric_value(value) -> bool:
    return value is None or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


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


@app.get("/cloud/aws/ec2/volumes")
def aws_ec2_volumes(request: Request, region: str | None = None, max_results: int = 500, next_token: str | None = None, unattached_only: bool = False):
    """Return paginated EBS inventory, scoped to owned volumes in token mode."""
    _validate_ec2_region(region)
    if not 5 <= max_results <= 500:
        raise HTTPException(status_code=400, detail="max_results must be between 5 and 500")
    if next_token is not None and (not next_token or len(next_token) > 4096):
        raise HTTPException(status_code=400, detail="next_token must contain 1 to 4096 characters")
    result = _aws_resource_result(lambda: aws_service.get_ec2_volumes(
        max_results=max_results, next_token=next_token, unattached_only=unattached_only,
        **({"region": region} if region else {})
    ))
    volumes = result.get("volumes")
    if not isinstance(volumes, list):
        _raise_aws_resource_unavailable()
    if result.get("next_token") is not None and (not isinstance(result["next_token"], str) or not result["next_token"]):
        _raise_aws_resource_unavailable()
    for volume in volumes:
        if (
            not isinstance(volume, dict) or not isinstance(volume.get("volume_id"), str)
            or not re.fullmatch(r"vol-[0-9a-fA-F]{8,17}", volume["volume_id"])
            or not isinstance(volume.get("state"), str)
            or not isinstance(volume.get("size_gib"), int) or isinstance(volume.get("size_gib"), bool)
            or volume["size_gib"] < 0
            or not isinstance(volume.get("encrypted"), bool)
            or (volume.get("volume_type") is not None and not isinstance(volume["volume_type"], str))
            or (volume.get("kms_key_id") is not None and not isinstance(volume["kms_key_id"], str))
            or (volume.get("availability_zone") is not None and not isinstance(volume["availability_zone"], str))
            or (volume.get("create_time") is not None and not isinstance(volume["create_time"], str))
            or any(volume.get(field) is not None and (not isinstance(volume[field], int) or isinstance(volume[field], bool) or volume[field] < 0) for field in ("iops", "throughput"))
            or not isinstance(volume.get("tags"), dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in volume["tags"].items())
            or not isinstance(volume.get("attachments"), list)
            or any(not isinstance(a, dict) or not isinstance(a.get("instance_id"), str) or any(a.get(k) is not None and not isinstance(a[k], str) for k in ("device", "state")) for a in volume["attachments"])
        ):
            _raise_aws_resource_unavailable()
    if result.get("is_truncated") != bool(result.get("next_token")):
        _raise_aws_resource_unavailable()
    if getattr(request.state, "tenant_scoped", False):
        result = dict(result)
        result["volumes"] = [v for v in volumes if _resource_tenant({"tags": v["tags"]}) == request.state.tenant_id]
    return result


@app.get("/cloud/aws/ec2/snapshots")
def aws_ec2_snapshots(request: Request, region: str | None = None, max_results: int = 100, next_token: str | None = None):
    """Return paginated, account-owned EBS snapshots; token users see owned tenant tags only."""
    _validate_ec2_region(region)
    if not 5 <= max_results <= 1000:
        raise HTTPException(status_code=400, detail="max_results must be between 5 and 1000")
    if next_token is not None and (not next_token or len(next_token) > 4096):
        raise HTTPException(status_code=400, detail="next_token must contain 1 to 4096 characters")
    result = _aws_resource_result(lambda: aws_service.get_ec2_snapshots(
        max_results=max_results, next_token=next_token, **({"region": region} if region else {})
    ))
    snapshots = result.get("snapshots")
    if not isinstance(snapshots, list):
        _raise_aws_resource_unavailable()
    if result.get("next_token") is not None and (not isinstance(result["next_token"], str) or not result["next_token"]):
        _raise_aws_resource_unavailable()
    for snapshot in snapshots:
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("snapshot_id"), str)
            or not re.fullmatch(r"snap-[0-9a-fA-F]{8,17}", snapshot["snapshot_id"])
            or not isinstance(snapshot.get("state"), str)
            or not isinstance(snapshot.get("size_gib"), int) or isinstance(snapshot.get("size_gib"), bool) or snapshot["size_gib"] < 0
            or not isinstance(snapshot.get("encrypted"), bool)
            or any(snapshot.get(field) is not None and not isinstance(snapshot[field], str) for field in ("volume_id", "kms_key_id", "description", "start_time"))
            or not isinstance(snapshot.get("tags"), dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in snapshot["tags"].items())
        ):
            _raise_aws_resource_unavailable()
    if result.get("is_truncated") != bool(result.get("next_token")):
        _raise_aws_resource_unavailable()
    if getattr(request.state, "tenant_scoped", False):
        result = dict(result)
        result["snapshots"] = [item for item in snapshots if _resource_tenant({"tags": item["tags"]}) == request.state.tenant_id]
    return result


@app.get("/cloud/aws/rds/instances")
def aws_rds_instances(request: Request, region: str | None = None, max_records: int = 100, marker: str | None = None,
                      engine: str | None = None, status: str | None = None):
    """Return a tenant-filtered, paginated view of RDS database instances."""
    _validate_ec2_region(region)
    if not 20 <= max_records <= 100:
        raise HTTPException(status_code=400, detail="max_records must be between 20 and 100")
    if marker is not None and (not marker or len(marker) > 4096):
        raise HTTPException(status_code=400, detail="marker must contain 1 to 4096 characters")
    if engine is not None and (not engine or len(engine) > 64 or not re.fullmatch(r"[a-z][a-z0-9-]*", engine)):
        raise HTTPException(status_code=400, detail="engine must be a valid RDS engine name")
    if status is not None and (not status or len(status) > 64 or not re.fullmatch(r"[a-z][a-z0-9-]*", status)):
        raise HTTPException(status_code=400, detail="status must be a valid RDS instance status")
    result = _aws_resource_result(lambda: aws_service.get_rds_instances(
        max_records=max_records, marker=marker, engine=engine, status=status,
        **({"region": region} if region else {})
    ))
    instances = result.get("instances")
    if not isinstance(instances, list) or result.get("is_truncated") != bool(result.get("next_marker")):
        _raise_aws_resource_unavailable()
    next_marker = result.get("next_marker")
    if next_marker is not None and (not isinstance(next_marker, str) or not next_marker):
        _raise_aws_resource_unavailable()
    for item in instances:
        invalid = not isinstance(item, dict)
        if not invalid:
            invalid = (
                not isinstance(item.get("identifier"), str)
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", item.get("identifier", ""))
                or not isinstance(item.get("arn"), str) or not item.get("arn", "").startswith("arn:")
                or any(item.get(key) is not None and not isinstance(item[key], str) for key in
                       ("engine", "engine_version", "status", "instance_class", "availability_zone", "endpoint"))
                or (item.get("storage_gib") is not None and (not isinstance(item["storage_gib"], int) or isinstance(item["storage_gib"], bool) or item["storage_gib"] < 0))
                or any(not isinstance(item.get(key), bool) for key in ("encrypted", "multi_az"))
                or any(item.get(key) is not None and not isinstance(item.get(key), bool)
                       for key in ("publicly_accessible", "deletion_protection"))
                or (item.get("backup_retention_days") is not None and (not isinstance(item.get("backup_retention_days"), int)
                    or isinstance(item.get("backup_retention_days"), bool)
                    or not 0 <= item["backup_retention_days"] <= 35))
                or (item.get("port") is not None and (not isinstance(item["port"], int) or isinstance(item["port"], bool) or not 1 <= item["port"] <= 65535))
                or not isinstance(item.get("tags"), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item["tags"].items())
            )
        if invalid:
            _raise_aws_resource_unavailable()
    if getattr(request.state, "tenant_scoped", False):
        result = dict(result)
        result["instances"] = [item for item in instances if _resource_tenant({"tags": item["tags"]}) == request.state.tenant_id]
    return result


@app.get("/cloud/aws/rds/snapshots")
def aws_rds_snapshots(request: Request, region: str | None = None, max_records: int = 100, marker: str | None = None):
    """Return a tenant-filtered, paginated view of RDS recovery snapshots."""
    _validate_ec2_region(region)
    if not 20 <= max_records <= 100:
        raise HTTPException(status_code=400, detail="max_records must be between 20 and 100")
    if marker is not None and (not marker or len(marker) > 4096):
        raise HTTPException(status_code=400, detail="marker must contain 1 to 4096 characters")
    result = _aws_resource_result(lambda: aws_service.get_rds_snapshots(
        max_records=max_records, marker=marker, **({"region": region} if region else {})
    ))
    snapshots = result.get("snapshots")
    if not isinstance(snapshots, list) or result.get("is_truncated") != bool(result.get("next_marker")):
        _raise_aws_resource_unavailable()
    next_marker = result.get("next_marker")
    if next_marker is not None and (not isinstance(next_marker, str) or not next_marker):
        _raise_aws_resource_unavailable()
    for item in snapshots:
        invalid = not isinstance(item, dict)
        if not invalid:
            invalid = (
                not isinstance(item.get("identifier"), str) or not item["identifier"]
                or not isinstance(item.get("arn"), str) or not item["arn"].startswith("arn:")
                or any(item.get(key) is not None and not isinstance(item[key], str)
                       for key in ("db_instance_identifier", "engine", "status", "snapshot_type", "kms_key_id", "snapshot_create_time"))
                or (item.get("storage_gib") is not None and (not isinstance(item["storage_gib"], int)
                    or isinstance(item["storage_gib"], bool) or item["storage_gib"] < 0))
                or (item.get("encrypted") is not None and not isinstance(item["encrypted"], bool))
                or not isinstance(item.get("tags"), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in item["tags"].items())
            )
        if invalid:
            _raise_aws_resource_unavailable()
    if getattr(request.state, "tenant_scoped", False):
        result = dict(result)
        result["snapshots"] = [item for item in snapshots if _resource_tenant({"tags": item["tags"]}) == request.state.tenant_id]
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


def _validate_s3_bucket_contract(result: dict, bucket_name: str, contract: str) -> dict:
    """Fail closed when a healthy S3 configuration result violates its API shape."""
    if (
        not isinstance(result, dict)
        or result.get("status") != "healthy"
        or result.get("service", "s3") != "s3"
        or ("bucket" in result and result["bucket"] != bucket_name)
    ):
        _raise_aws_resource_unavailable()

    def count_fields(rules_key="rules"):
        rules = result.get(rules_key)
        if (
            not isinstance(rules, list)
            or any(not isinstance(rule, dict) for rule in rules)
            or not isinstance(result.get("configured"), bool)
            or result["configured"] != bool(rules)
            or not isinstance(result.get("rule_count"), int)
            or isinstance(result.get("rule_count"), bool)
            or result["rule_count"] != len(rules)
        ):
            _raise_aws_resource_unavailable()
        return rules

    if contract == "details":
        region = result.get("region")
        valid = (
            isinstance(result.get("bucket"), str)
            and isinstance(region, str)
            and bool(region.strip())
        )
    elif contract == "versioning":
        versioning = result.get("versioning")
        mfa_delete = result.get("mfa_delete")
        valid = (
            isinstance(versioning, str)
            and versioning in {"disabled", "enabled", "suspended"}
            and isinstance(mfa_delete, str)
            and mfa_delete in {"disabled", "enabled"}
        )
    elif contract in {"lifecycle", "replication"}:
        rules = count_fields()
        enabled = result.get("enabled_rule_count")
        valid = (
            isinstance(enabled, int)
            and not isinstance(enabled, bool)
            and enabled == sum(rule.get("Status") == "Enabled" for rule in rules)
        )
    elif contract == "logging":
        destination = result.get("destination_bucket")
        prefix = result.get("destination_prefix")
        grants = result.get("target_grants")
        valid = (
            isinstance(result.get("configured"), bool)
            and (destination is None or isinstance(destination, str))
            and isinstance(prefix, str)
            and isinstance(grants, list)
            and all(isinstance(grant, dict) for grant in grants)
            and result["configured"] == (destination is not None)
        )
    elif contract == "encryption":
        rules = count_fields()
        valid = all(
            isinstance(rule.get("ApplyServerSideEncryptionByDefault"), dict)
            and isinstance(
                rule["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm"), str
            )
            and bool(rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"].strip())
            for rule in rules
        )
    elif contract == "object-lock":
        enabled = result.get("enabled")
        retention = result.get("default_retention")
        valid = result.get("bucket") == bucket_name and isinstance(enabled, bool) and (
            retention is None
            or (
                enabled and isinstance(retention, dict)
                and isinstance(retention.get("DefaultRetention"), dict)
                and retention["DefaultRetention"].get("Mode") in {"GOVERNANCE", "COMPLIANCE"}
                and (
                    isinstance(retention["DefaultRetention"].get("Days"), int)
                    and not isinstance(retention["DefaultRetention"].get("Days"), bool)
                    and retention["DefaultRetention"]["Days"] > 0
                    and "Years" not in retention["DefaultRetention"]
                    or isinstance(retention["DefaultRetention"].get("Years"), int)
                    and not isinstance(retention["DefaultRetention"].get("Years"), bool)
                    and retention["DefaultRetention"]["Years"] > 0
                    and "Days" not in retention["DefaultRetention"]
                )
            )
        )
    elif contract == "tags":
        tags = result.get("tags")
        valid = isinstance(tags, dict) and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in tags.items()
        )
    elif contract == "policy":
        policy = result.get("policy")
        configured = result.get("configured")
        valid = isinstance(configured, bool) and (
            (configured and isinstance(policy, dict))
            or (not configured and policy is None)
        )
    else:
        valid = False
    if not valid:
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/s3/buckets/{bucket_name}")
def aws_s3_bucket_details(bucket_name: str, request: Request):
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_details(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "details")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/versioning")
def aws_s3_bucket_versioning(bucket_name: str, request: Request):
    """Return bucket versioning state after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_versioning(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "versioning")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/lifecycle")
def aws_s3_bucket_lifecycle(bucket_name: str, request: Request):
    """Inspect lifecycle rules after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_lifecycle(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "lifecycle")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/replication")
def aws_s3_bucket_replication(bucket_name: str, request: Request):
    """Inspect replication rules after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_replication(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "replication")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/logging")
def aws_s3_bucket_logging(bucket_name: str, request: Request):
    """Inspect server access logging after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_logging(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "logging")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/encryption")
def aws_s3_bucket_encryption(bucket_name: str, request: Request):
    """Inspect default bucket encryption after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_encryption(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "encryption")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/tags")
def aws_s3_bucket_tags(bucket_name: str, request: Request):
    """Review bucket metadata after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_tags(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "tags")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/object-lock")
def aws_s3_bucket_object_lock(bucket_name: str, request: Request):
    """Inspect Object Lock retention after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_object_lock(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "object-lock")


@app.get("/cloud/aws/s3/buckets/{bucket_name}/policy")
def aws_s3_bucket_policy(bucket_name: str, request: Request):
    """Review a bucket policy after verifying tenant ownership."""
    _require_tenant_s3_bucket(request, bucket_name)
    result = _aws_resource_result(lambda: aws_service.get_s3_bucket_policy(bucket_name))
    return _validate_s3_bucket_contract(result, bucket_name, "policy")


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

    result = _aws_resource_result(lambda: aws_service.get_s3_objects(
        bucket_name,
        prefix=prefix,
        max_keys=max_keys,
        continuation_token=continuation_token,
        delimiter=delimiter,
    ))
    objects = result.get("objects")
    common_prefixes = result.get("common_prefixes")
    truncated = result.get("is_truncated")
    next_token = result.get("next_continuation_token")
    if (
        result.get("service") != "s3"
        or result.get("bucket") != bucket_name
        or result.get("prefix") != prefix
        or not isinstance(objects, list)
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("key"), str)
            or not item["key"]
            or not isinstance(item.get("size"), int)
            or isinstance(item["size"], bool)
            or item["size"] < 0
            or (
                item.get("last_modified") is not None
                and not isinstance(item["last_modified"], str)
            )
            for item in objects
        )
        or not isinstance(common_prefixes, list)
        or any(not isinstance(item, str) or not item for item in common_prefixes)
        or not isinstance(truncated, bool)
        or (
            next_token is not None
            and (not isinstance(next_token, str) or not next_token)
        )
        or (truncated and next_token is None)
        or (not truncated and next_token is not None)
    ):
        _raise_aws_resource_unavailable()
    return result


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
    result = _aws_resource_result(lambda: (
        aws_service.get_s3_object_metadata(bucket_name, key)
        if version_id is None
        else aws_service.get_s3_object_metadata(bucket_name, key, version_id)
    ))
    obj = result.get("object")
    if (
        result.get("service") not in (None, "s3")
        or result.get("bucket") != bucket_name
        or not isinstance(obj, dict)
        or obj.get("key") != key
        or (obj.get("version_id") is not None and not isinstance(obj["version_id"], str))
        or (version_id is not None and obj.get("version_id") != version_id)
        or (obj.get("size") is not None and (
            not isinstance(obj.get("size"), int)
            or isinstance(obj.get("size"), bool)
            or obj["size"] < 0
        ))
        or any(
            obj.get(field) is not None and not isinstance(obj.get(field), str)
            for field in (
                "content_type", "etag", "last_modified", "storage_class",
                "server_side_encryption",
            )
        )
        or ("user_metadata" in obj and not isinstance(obj["user_metadata"], dict))
        or any(
            not isinstance(name, str) or not isinstance(value, str)
            for name, value in obj.get("user_metadata", {}).items()
        )
    ):
        _raise_aws_resource_unavailable()
    return result


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
    result = _aws_resource_result(lambda: aws_service.get_s3_object_versions(
        bucket_name, prefix=prefix, key_marker=key_marker,
        version_id_marker=version_id_marker, max_keys=max_keys,
    ))
    versions = result.get("versions")
    if (
        result.get("service") != "s3"
        or result.get("bucket") != bucket_name
        or not isinstance(versions, list)
        or not isinstance(result.get("is_truncated"), bool)
        or any(
            not isinstance(version, dict)
            or not isinstance(version.get("key"), str)
            or not version["key"]
            or not isinstance(version.get("version_id"), str)
            or not isinstance(version.get("is_latest"), bool)
            or not isinstance(version.get("delete_marker"), bool)
            or (version.get("last_modified") is not None
                and not isinstance(version.get("last_modified"), str))
            or (version.get("size") is not None
                and (not isinstance(version.get("size"), int)
                     or isinstance(version.get("size"), bool) or version["size"] < 0))
            or any(version.get(field) is not None and not isinstance(version.get(field), str)
                   for field in ("etag", "storage_class"))
            for version in versions
        )
        or any(
            result.get(field) is not None and not isinstance(result.get(field), str)
            for field in ("next_key_marker", "next_version_id_marker")
        )
        or (result["is_truncated"] and not result.get("next_key_marker"))
    ):
        _raise_aws_resource_unavailable()
    return result


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
    result = _aws_resource_result(lambda: (
        aws_service.create_s3_object_download_url(bucket_name, key, version_id)
        if version_id is not None
        else aws_service.create_s3_object_download_url(bucket_name, key)
    ))
    url = result.get("url") if isinstance(result, dict) else None
    try:
        parsed_url = urlsplit(url) if isinstance(url, str) else None
        valid_url = (
            parsed_url is not None
            and parsed_url.scheme in {"http", "https"}
            and bool(parsed_url.netloc)
            and parsed_url.hostname is not None
            and parsed_url.username is None
            and parsed_url.password is None
        )
    except ValueError:
        valid_url = False
    if (
        not isinstance(result, dict)
        or result.get("service") != "s3"
        or result.get("status") != "healthy"
        or result.get("bucket") != bucket_name
        or result.get("key") != key
        or result.get("expires_in") != 300
        or not valid_url
    ):
        _raise_aws_resource_unavailable()
    if version_id is not None and result.get("version_id") != version_id:
        _raise_aws_resource_unavailable()
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
    _validate_ec2_instance_result(instance, instance_id)
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
    result = _aws_resource_result(lambda: aws_service.get_ec2_cpu_utilization(
        instance_id, **({"region": region} if region else {})
    ))
    datapoints = result.get("datapoints", [])
    if (
        result.get("service") != "cloudwatch"
        or result.get("instance_id") != instance_id
        or result.get("metric") != "CPUUtilization"
        or not _valid_metric_value(result.get("value"))
        or not isinstance(datapoints, list)
        or any(
            not isinstance(point, dict)
            or not isinstance(point.get("timestamp"), str)
            or not point["timestamp"]
            or not _valid_metric_value(point.get("value"))
            for point in datapoints
        )
        or ("lookback_hours" in result and not _valid_metric_value(result["lookback_hours"]))
        or ("timestamp" in result and result["timestamp"] is not None and not isinstance(result["timestamp"], str))
    ):
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/network")
def aws_ec2_network_utilization(instance_id: str, request: Request, region: str | None = None):
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    result = _aws_resource_result(lambda: aws_service.get_ec2_network_utilization(
        instance_id, **({"region": region} if region else {})
    ))
    metrics = result.get("metrics")
    datapoints = result.get("datapoints")
    metric_names = ("NetworkIn", "NetworkOut")
    if (
        result.get("service") != "cloudwatch"
        or result.get("instance_id") != instance_id
        or not isinstance(metrics, dict)
        or set(metrics) != set(metric_names)
        or any(not _valid_metric_value(metrics[name]) for name in metric_names)
        or not isinstance(datapoints, dict)
        or set(datapoints) != set(metric_names)
        or any(
            not isinstance(datapoints[name], list)
            or any(
                not isinstance(point, dict)
                or not isinstance(point.get("timestamp"), str)
                or not point["timestamp"]
                or not _valid_metric_value(point.get("value"))
                for point in datapoints[name]
            )
            for name in metric_names
        )
        or ("lookback_hours" in result and not _valid_metric_value(result["lookback_hours"]))
    ):
        _raise_aws_resource_unavailable()
    return result


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
    result = _aws_resource_result(lambda: aws_service.get_ec2_instance_status(
        instance_id, **({"region": region} if region else {})
    ))
    status_fields = ("instance_status", "system_status", "state")
    events = result.get("events")
    if (
        result.get("service") != "ec2"
        or result.get("instance_id") != instance_id
        or any(
            result.get(field) is not None and not isinstance(result.get(field), str)
            for field in status_fields
        )
        or not isinstance(events, list)
        or any(
            not isinstance(event, dict)
            or any(
                key not in {"Code", "Description", "NotBefore", "NotAfter"}
                or not isinstance(value, (str, datetime))
                for key, value in event.items()
            )
            for event in events
        )
    ):
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/volumes")
def aws_ec2_instance_volumes(instance_id: str, request: Request, region: str | None = None):
    """Inspect attached EBS encryption only after verifying instance ownership."""
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    result = _aws_resource_result(lambda: aws_service.get_ec2_instance_volumes(
        instance_id, **({"region": region} if region else {})
    ))
    volumes = result.get("volumes")

    def valid_volume(volume):
        if not isinstance(volume, dict):
            return False
        if not isinstance(volume.get("volume_id"), str) or not volume["volume_id"].startswith("vol-"):
            return False
        if volume.get("encrypted") is not None and not isinstance(volume.get("encrypted"), bool):
            return False
        if volume.get("kms_key_id") is not None and not isinstance(volume.get("kms_key_id"), str):
            return False
        size = volume.get("size_gib")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool)):
            return False
        if any(
            volume.get(key) is not None and not isinstance(volume.get(key), str)
            for key in ("volume_type", "state")
        ):
            return False
        attachments = volume.get("attachments", [])
        return isinstance(attachments, list) and all(
            isinstance(attachment, dict)
            and all(
                attachment.get(key) is None or isinstance(attachment.get(key), str)
                for key in ("device", "state")
            )
            for attachment in attachments
        )

    if (
        result.get("service") != "ec2"
        or result.get("instance_id") != instance_id
        or not isinstance(volumes, list)
        or any(not valid_volume(volume) for volume in volumes)
    ):
        _raise_aws_resource_unavailable()
    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/security-groups")
def aws_ec2_instance_security_groups(instance_id: str, request: Request, region: str | None = None):
    """Inspect security group rules only after verifying instance ownership."""
    _validate_ec2_instance_id(instance_id)
    _validate_ec2_region(region)
    _require_tenant_ec2_instance(request, instance_id, region)
    result = _aws_resource_result(lambda: aws_service.get_ec2_instance_security_groups(
        instance_id, **({"region": region} if region else {})
    ))
    groups = result.get("security_groups")
    def valid_rule(rule, direction):
        if not isinstance(rule, dict):
            return False
        if rule.get("protocol") is not None and not isinstance(rule["protocol"], str):
            return False
        if any(rule.get(key) is not None and (not isinstance(rule[key], int) or isinstance(rule[key], bool)) for key in ("from_port", "to_port")):
            return False
        for key in ("ipv4_ranges", "ipv6_ranges"):
            if not isinstance(rule.get(key), list) or any(
                not isinstance(item, dict) or not isinstance(item.get("cidr"), str)
                or (item.get("description") is not None and not isinstance(item.get("description"), str))
                for item in rule[key]
            ):
                return False
        if not isinstance(rule.get("prefix_list_ids"), list) or any(not isinstance(value, str) for value in rule["prefix_list_ids"]):
            return False
        peer_groups_key = "source_security_groups" if direction == "ingress" else "destination_security_groups"
        pairs = rule.get(peer_groups_key)
        return isinstance(pairs, list) and all(
            isinstance(item, dict) and isinstance(item.get("group_id"), str)
            and all(item.get(key) is None or isinstance(item[key], str) for key in ("owner_id", "vpc_id"))
            for item in pairs
        )
    if (
        result.get("service") != "ec2" or result.get("instance_id") != instance_id
        or not isinstance(groups, list) or any(
            not isinstance(group, dict) or not isinstance(group.get("group_id"), str)
            or any(group.get(key) is not None and not isinstance(group[key], str) for key in ("group_name", "description", "vpc_id"))
            or not isinstance(group.get("ingress_rules"), list)
            or any(not valid_rule(rule, "ingress") for rule in group["ingress_rules"])
            or not isinstance(group.get("egress_rules"), list)
            or any(not valid_rule(rule, "egress") for rule in group["egress_rules"])
            for group in groups
        )
    ):
        _raise_aws_resource_unavailable()
    return result


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
    result = _aws_resource_result(lambda: aws_service.get_ec2_alarms(
        instance_id,
        next_token=next_token,
        **({"region": region} if region else {}),
    ))
    alarms = result.get("alarms")
    if (
        result.get("service") != "cloudwatch"
        or result.get("instance_id") != instance_id
        or not isinstance(alarms, list)
        or (result.get("next_token") is not None and not isinstance(result.get("next_token"), str))
        or any(not _valid_ec2_alarm(alarm) for alarm in alarms)
    ):
        _raise_aws_resource_unavailable()
    return result


def _valid_ec2_alarm(alarm: object) -> bool:
    if not isinstance(alarm, dict):
        return False
    if not isinstance(alarm.get("AlarmName"), str) or not alarm["AlarmName"].strip():
        return False
    string_fields = (
        "AlarmName", "AlarmDescription", "StateValue", "StateReason", "MetricName",
        "Namespace", "ComparisonOperator", "TreatMissingData",
    )
    if any(key in alarm and alarm[key] is not None and not isinstance(alarm[key], str) for key in string_fields):
        return False
    number_fields = ("Threshold",)
    if any(
        key in alarm and alarm[key] is not None
        and (not isinstance(alarm[key], (int, float)) or isinstance(alarm[key], bool)
             or not isfinite(alarm[key]))
        for key in number_fields
    ):
        return False
    return all(
        key not in alarm or alarm[key] is None
        or (isinstance(alarm[key], int) and not isinstance(alarm[key], bool) and alarm[key] > 0)
        for key in ("Period", "EvaluationPeriods")
    )


@app.get("/cloud/aws/ec2/alarms")
def aws_ec2_fleet_alarms(request: Request, region: str | None = None):
    """List regional EC2 CPU alarms, scoped to the authenticated tenant."""
    _validate_ec2_region(region)
    result = _aws_resource_result(lambda: aws_service.get_ec2_fleet_alarms(
        **({"region": region} if region else {})
    ))
    alarms = result.get("alarms")
    if (
        result.get("service") != "cloudwatch"
        or not isinstance(alarms, list)
        or any(
            not _valid_ec2_alarm(alarm)
            or not isinstance(alarm.get("instance_ids"), list)
            or any(
                not isinstance(instance_id, str)
                or not re.fullmatch(r"i-[0-9a-fA-F]{8,17}", instance_id)
                for instance_id in alarm["instance_ids"]
            )
            for alarm in alarms
        )
    ):
        _raise_aws_resource_unavailable()
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
    result = _aws_resource_result(lambda: aws_service.get_ec2_metrics(
        instance_id, lookback_hours=lookback_hours,
        **({"region": region} if region else {}),
    ))
    if (
        result.get("service") != "ec2"
        or result.get("instance_id") != instance_id
        or any(not isinstance(result.get(field), dict) for field in ("cpu", "network", "instance_status"))
        or ("status_checks" in result and not isinstance(result["status_checks"], dict))
    ):
        _raise_aws_resource_unavailable()
    return result


