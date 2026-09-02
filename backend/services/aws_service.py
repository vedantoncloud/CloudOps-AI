import boto3
from datetime import datetime, timedelta, timezone
from botocore.exceptions import BotoCoreError, ClientError


class AWSService:
    def get_status(self):
        try:
            sts = boto3.client("sts")
            identity = sts.get_caller_identity()

            ec2 = boto3.client("ec2")
            response = ec2.describe_instances()

            total_instances = 0
            running_instances = 0
            stopped_instances = 0

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    total_instances += 1

                    state = instance.get("State", {}).get("Name")

                    if state == "running":
                        running_instances += 1
                    elif state == "stopped":
                        stopped_instances += 1

            return {
                "provider": "AWS",
                "status": "connected",
                "account_id": identity.get("Account"),
                "arn": identity.get("Arn"),
                "services": {
                    "sts": "healthy",
                    "ec2": {
                        "status": "healthy",
                        "total_instances": total_instances,
                        "running_instances": running_instances,
                        "stopped_instances": stopped_instances,
                    },
                },
                "message": "AWS services are healthy",
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "provider": "AWS",
                "status": "disconnected",
                "message": "Unable to connect to AWS services",
                "error": str(error),
            }

    def get_service_health(self, service_name):
        if service_name == "sts":
            try:
                sts = boto3.client("sts")
                sts.get_caller_identity()

                return {
                    "service": "sts",
                    "status": "healthy",
                }

            except (BotoCoreError, ClientError) as error:
                return {
                    "service": "sts",
                    "status": "unhealthy",
                    "error": str(error),
                }

        if service_name == "ec2":
            try:
                ec2 = boto3.client("ec2")
                ec2.describe_instances()

                return {
                    "service": "ec2",
                    "status": "healthy",
                }

            except (BotoCoreError, ClientError) as error:
                return {
                    "service": "ec2",
                    "status": "unhealthy",
                    "error": str(error),
                }

        return {
            "service": service_name,
            "status": "unsupported",
            "message": "Service health check is not supported yet",
        }

    def get_ec2_summary(self):
        try:
            ec2 = boto3.client("ec2")
            response = ec2.describe_instances()

            total_instances = 0
            running_instances = 0
            stopped_instances = 0

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    total_instances += 1

                    state = instance.get("State", {}).get("Name")

                    if state == "running":
                        running_instances += 1
                    elif state == "stopped":
                        stopped_instances += 1

            return {
                "service": "ec2",
                "status": "healthy",
                "total_instances": total_instances,
                "running_instances": running_instances,
                "stopped_instances": stopped_instances,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_ec2_instances(self, state=None, tag=None):
        try:
            ec2 = boto3.client("ec2")

            filters = []

            if state:
                filters.append({
                    "Name": "instance-state-name",
                    "Values": [state],
                })

            if tag:
                if ":" not in tag:
                    return {
                        "service": "ec2",
                        "status": "invalid",
                        "message": "Tag must be in key:value format",
                    }

                key, value = tag.split(":", 1)

                if not key or not value:
                    return {
                        "service": "ec2",
                        "status": "invalid",
                        "message": "Tag must be in key:value format",
                    }

                filters.append({
                    "Name": f"tag:{key}",
                    "Values": [value],
                })

            if filters:
                response = ec2.describe_instances(Filters=filters)
            else:
                response = ec2.describe_instances()

            instances = []

            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    name = None
                    tags = {}

                    for instance_tag in instance.get("Tags", []):
                        key = instance_tag.get("Key")
                        value = instance_tag.get("Value")

                        if key:
                            tags[key] = value

                        if key == "Name":
                            name = value

                    instances.append({
                        "instance_id": instance.get("InstanceId"),
                        "name": name,
                        "state": instance.get("State", {}).get("Name"),
                        "instance_type": instance.get("InstanceType"),
                        "availability_zone": instance.get("Placement", {}).get("AvailabilityZone"),
                        "private_ip": instance.get("PrivateIpAddress"),
                        "tags": tags,
                    })

            return {
                "service": "ec2",
                "status": "healthy",
                "instances": instances,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_s3_buckets(self):
        try:
            s3 = boto3.client("s3")
            response = s3.list_buckets()

            buckets = []

            for bucket in response.get("Buckets", []):
                buckets.append({
                    "name": bucket.get("Name"),
                    "creation_date": (
                        bucket.get("CreationDate").isoformat()
                        if bucket.get("CreationDate")
                        else None
                    ),
                })

            return {
                "service": "s3",
                "status": "healthy",
                "buckets": buckets,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_s3_bucket_details(self, bucket_name):
        try:
            s3 = boto3.client("s3")

            response = s3.get_bucket_location(
                Bucket=bucket_name
            )

            region = response.get("LocationConstraint")

            if region is None:
                region = "us-east-1"

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "region": region,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_objects(self, bucket_name, prefix=None, max_keys=None):
        try:
            s3 = boto3.client("s3")

            objects = []
            continuation_token = None

            while True:
                params = {
                    "Bucket": bucket_name,
                }

                if prefix:
                    params["Prefix"] = prefix

                if max_keys:
                    params["MaxKeys"] = min(max_keys, 1000)

                if continuation_token:
                    params["ContinuationToken"] = continuation_token

                response = s3.list_objects_v2(**params)

                for obj in response.get("Contents", []):
                    objects.append({
                        "key": obj.get("Key"),
                        "size": obj.get("Size"),
                        "last_modified": (
                            obj.get("LastModified").isoformat()
                            if obj.get("LastModified")
                            else None
                        ),
                    })

                    if max_keys and len(objects) >= max_keys:
                        objects = objects[:max_keys]
                        break

                if max_keys and len(objects) >= max_keys:
                    break

                if not response.get("IsTruncated"):
                    break

                continuation_token = response.get("NextContinuationToken")

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "objects": objects,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_ec2_cpu_utilization(self, instance_id):
        try:
            cloudwatch = boto3.client("cloudwatch")

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=10)

            response = cloudwatch.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[
                    {
                        "Name": "InstanceId",
                        "Value": instance_id,
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=["Average"],
            )

            datapoints = response.get("Datapoints", [])

            if not datapoints:
                return {
                    "service": "cloudwatch",
                    "status": "healthy",
                    "instance_id": instance_id,
                    "metric": "CPUUtilization",
                    "value": None,
                }

            latest = max(
                datapoints,
                key=lambda datapoint: datapoint.get("Timestamp")
            )

            return {
                "service": "cloudwatch",
                "status": "healthy",
                "instance_id": instance_id,
                "metric": "CPUUtilization",
                "value": latest.get("Average"),
                "timestamp": (
                    latest.get("Timestamp").isoformat()
                    if latest.get("Timestamp")
                    else None
                ),
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "cloudwatch",
                "status": "unhealthy",
                "instance_id": instance_id,
                "error": str(error),
            }

    def get_ec2_network_utilization(self, instance_id):
        try:
            cloudwatch = boto3.client("cloudwatch")

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(minutes=10)

            metrics = {}

            for metric_name in ["NetworkIn", "NetworkOut"]:
                response = cloudwatch.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName=metric_name,
                    Dimensions=[
                        {
                            "Name": "InstanceId",
                            "Value": instance_id,
                        }
                    ],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=300,
                    Statistics=["Average"],
                )

                datapoints = response.get("Datapoints", [])

                if datapoints:
                    latest = max(
                        datapoints,
                        key=lambda datapoint: datapoint.get("Timestamp")
                    )

                    metrics[metric_name] = latest.get("Average")
                else:
                    metrics[metric_name] = None

            return {
                "service": "cloudwatch",
                "status": "healthy",
                "instance_id": instance_id,
                "metrics": metrics,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "cloudwatch",
                "status": "unhealthy",
                "instance_id": instance_id,
                "error": str(error),
            }

    def get_ec2_instance_status(self, instance_id):
        try:
            ec2 = boto3.client("ec2")

            response = ec2.describe_instance_status(
                InstanceIds=[instance_id],
                IncludeAllInstances=True,
            )

            statuses = response.get("InstanceStatuses", [])

            if not statuses:
                return {
                    "service": "ec2",
                    "status": "healthy",
                    "instance_id": instance_id,
                    "instance_status": None,
                    "system_status": None,
                    "state": None,
                }

            instance = statuses[0]

            instance_state = instance.get("InstanceState", {})
            instance_status = instance.get("InstanceStatus", {})
            system_status = instance.get("SystemStatus", {})

            return {
                "service": "ec2",
                "status": "healthy",
                "instance_id": instance_id,
                "instance_status": instance_status.get("Status"),
                "system_status": system_status.get("Status"),
                "state": instance_state.get("Name"),
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "instance_id": instance_id,
                "error": str(error),
            }