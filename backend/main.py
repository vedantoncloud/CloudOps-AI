from fastapi import FastAPI, HTTPException

from services.aws_service import AWSService


app = FastAPI(
    title="CloudOps AI",
    description="AI-powered Cloud Operations Platform",
    version="0.1.0",
)


aws_service = AWSService()


@app.get("/")
def root():
    return {
        "message": "CloudOps AI is running",
        "version": "0.1.0",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "cloudops-ai",
    }


@app.get("/cloud/aws/status")
def aws_status():
    return aws_service.get_status()


@app.get("/cloud/aws/services/{service_name}")
def aws_service_health(service_name: str):
    return aws_service.get_service_health(service_name)


@app.get("/cloud/aws/ec2/summary")
def aws_ec2_summary():
    return aws_service.get_ec2_summary()


@app.get("/cloud/aws/ec2/instances")
def aws_ec2_instances(state: str = None, tag: str = None):
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

    return aws_service.get_ec2_instances(state, tag)


@app.get("/cloud/aws/s3/buckets")
def aws_s3_buckets():
    return aws_service.get_s3_buckets()


@app.get("/cloud/aws/s3/buckets/{bucket_name}")
def aws_s3_bucket_details(bucket_name: str):
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
    prefix: str = None,
    max_keys: int = None,
):
    if max_keys is not None and (max_keys <= 0 or max_keys > 1000):
        raise HTTPException(
            status_code=400,
            detail="max_keys must be between 1 and 1000",
        )

    result = aws_service.get_s3_objects(
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


@app.get("/cloud/aws/ec2/instances/{instance_id}/cpu")
def aws_ec2_cpu(instance_id: str):
    result = aws_service.get_ec2_cpu_utilization(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/network")
def aws_ec2_network_utilization(instance_id: str):
    result = aws_service.get_ec2_network_utilization(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/status")
def aws_ec2_instance_status(instance_id: str):
    result = aws_service.get_ec2_instance_status(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result


@app.get("/cloud/aws/ec2/instances/{instance_id}/metrics")
def aws_ec2_metrics(instance_id: str):
    result = aws_service.get_ec2_metrics(instance_id)

    if result["status"] == "unhealthy":
        raise HTTPException(
            status_code=403,
            detail=result["error"],
        )

    return result