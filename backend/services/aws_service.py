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
                        "availability_zone": instance.get("Placement", {}).get(
                            "AvailabilityZone"
                        ),
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

    def get_s3_object_statistics(self, bucket_name, prefix=None, max_keys=None):
        try:
            s3 = boto3.client("s3")

            total_objects = 0
            total_size = 0
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
                    total_objects += 1
                    total_size += obj.get("Size", 0) or 0

                    if max_keys and total_objects >= max_keys:
                        break

                if max_keys and total_objects >= max_keys:
                    break

                if not response.get("IsTruncated"):
                    break

                continuation_token = response.get("NextContinuationToken")

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "total_objects": total_objects,
                "total_size_bytes": total_size,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_largest_objects(self, bucket_name, prefix=None, max_keys=None, top_n=5):
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
                        "size": obj.get("Size", 0) or 0,
                        "last_modified": (
                            obj.get("LastModified").isoformat()
                            if obj.get("LastModified")
                            else None
                        ),
                    })

                if max_keys and len(objects) >= max_keys:
                    objects = objects[:max_keys]
                    break

                if not response.get("IsTruncated"):
                    break

                continuation_token = response.get("NextContinuationToken")

            objects.sort(
                key=lambda obj: obj["size"],
                reverse=True,
            )

            largest_objects = objects[:top_n]

            total_objects = len(objects)
            total_size_bytes = sum(obj["size"] for obj in objects)
            average_object_size_bytes = (
                total_size_bytes / total_objects
                if total_objects
                else 0
            )

            largest_object = largest_objects[0] if largest_objects else None

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "top_n": top_n,
                "total_objects": total_objects,
                "total_size_bytes": total_size_bytes,
                "average_object_size_bytes": average_object_size_bytes,
                "largest_object": largest_object,
                "objects": largest_objects,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_bucket_health(self, bucket_name, prefix=None, max_keys=None):
        try:
            insights = self.get_s3_largest_objects(
                bucket_name,
                prefix=prefix,
                max_keys=max_keys,
                top_n=1,
            )

            if insights["status"] == "unhealthy":
                return insights

            total_objects = insights["total_objects"]
            risks = []

            if total_objects == 0:
                risks.append({
                    "type": "empty_bucket",
                    "severity": "low",
                    "message": "Bucket contains no objects.",
                })

            health = "warning" if risks else "healthy"

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "health": health,
                "risk_count": len(risks),
                "risks": risks,
                "total_objects": total_objects,
                "total_size_bytes": insights["total_size_bytes"],
                "average_object_size_bytes": insights["average_object_size_bytes"],
                "largest_object": insights["largest_object"],
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_bucket_insights(self, bucket_name, prefix=None, max_keys=None):
        try:
            storage = self.get_s3_largest_objects(
                bucket_name,
                prefix=prefix,
                max_keys=max_keys,
                top_n=1,
            )

            if storage["status"] == "unhealthy":
                return storage

            total_objects = storage["total_objects"]
            total_size_bytes = storage["total_size_bytes"]
            average_object_size_bytes = storage["average_object_size_bytes"]
            largest_object = storage["largest_object"]

            insights = []

            if total_objects == 0:
                insights.append({
                    "type": "empty_bucket",
                    "severity": "low",
                    "message": "Bucket contains no objects.",
                    "recommendation": "Verify whether this bucket is still required.",
                })

            if largest_object and largest_object["size"] >= 1024 ** 3:
                insights.append({
                    "type": "large_object",
                    "severity": "medium",
                    "message": "Bucket contains an object larger than 1 GB.",
                    "recommendation": "Review the object and consider compression or lifecycle policies.",
                })

            if total_objects >= 100000:
                insights.append({
                    "type": "high_object_count",
                    "severity": "medium",
                    "message": "Bucket contains a very large number of objects.",
                    "recommendation": "Review object lifecycle and prefix organization to reduce management overhead.",
                })

            if total_objects >= 1000 and average_object_size_bytes <= 128 * 1024:
                insights.append({
                    "type": "many_small_objects",
                    "severity": "low",
                    "message": "Bucket contains many relatively small objects.",
                    "recommendation": "Consider combining small files where practical and review storage access patterns.",
                })

            health = "warning" if insights else "healthy"

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "health": health,
                "insight_count": len(insights),
                "insights": insights,
                "total_objects": total_objects,
                "total_size_bytes": total_size_bytes,
                "average_object_size_bytes": average_object_size_bytes,
                "largest_object": largest_object,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_bucket_optimization(self, bucket_name, prefix=None, max_keys=None):
        try:
            storage = self.get_s3_largest_objects(
                bucket_name,
                prefix=prefix,
                max_keys=max_keys,
                top_n=1,
            )

            if storage["status"] == "unhealthy":
                return storage

            total_objects = storage["total_objects"]
            total_size_bytes = storage["total_size_bytes"]
            average_object_size_bytes = storage["average_object_size_bytes"]
            largest_object = storage["largest_object"]

            recommendations = []

            if total_objects == 0:
                recommendations.append({
                    "type": "empty_bucket",
                    "priority": "low",
                    "message": "Bucket contains no objects.",
                    "recommendation": "Review whether the bucket is still required and remove unused buckets when appropriate.",
                })

            if largest_object and largest_object["size"] >= 5 * 1024 ** 3:
                recommendations.append({
                    "type": "very_large_object",
                    "priority": "medium",
                    "message": "Bucket contains an object larger than 5 GB.",
                    "recommendation": "Review large objects and consider compression, multipart-aware workflows, or lifecycle transitions where appropriate.",
                })

            if total_objects >= 1000 and average_object_size_bytes <= 128 * 1024:
                recommendations.append({
                    "type": "small_object_optimization",
                    "priority": "low",
                    "message": "Bucket contains many relatively small objects.",
                    "recommendation": "Consider consolidating small files where practical to reduce object-management overhead.",
                })

            if total_objects >= 100000:
                recommendations.append({
                    "type": "object_count_optimization",
                    "priority": "medium",
                    "message": "Bucket contains a very large number of objects.",
                    "recommendation": "Review lifecycle rules, retention requirements, and prefix organization to manage object growth.",
                })

            if total_size_bytes >= 100 * 1024 ** 3:
                recommendations.append({
                    "type": "large_storage_footprint",
                    "priority": "medium",
                    "message": "Bucket storage footprint exceeds 100 GB.",
                    "recommendation": "Review lifecycle policies and transition infrequently accessed data to appropriate storage classes.",
                })

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "recommendation_count": len(recommendations),
                "recommendations": recommendations,
                "total_objects": total_objects,
                "total_size_bytes": total_size_bytes,
                "average_object_size_bytes": average_object_size_bytes,
                "largest_object": largest_object,
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

    def get_ec2_metrics(self, instance_id):
        try:
            cpu = self.get_ec2_cpu_utilization(instance_id)
            network = self.get_ec2_network_utilization(instance_id)
            status = self.get_ec2_instance_status(instance_id)

            if (
                cpu["status"] == "unhealthy"
                or network["status"] == "unhealthy"
                or status["status"] == "unhealthy"
            ):
                return {
                    "service": "ec2",
                    "status": "unhealthy",
                    "instance_id": instance_id,
                    "cpu": cpu,
                    "network": network,
                    "instance_status": status,
                }

            return {
                "service": "ec2",
                "status": "healthy",
                "instance_id": instance_id,
                "cpu": cpu,
                "network": network,
                "instance_status": status,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "instance_id": instance_id,
                "error": str(error),
            }


    def get_ec2_insights(self, instance_id):
        try:
            metrics = self.get_ec2_metrics(instance_id)

            if metrics["status"] == "unhealthy":
                return metrics

            cpu = metrics["cpu"]
            network = metrics["network"]
            instance_status = metrics["instance_status"]

            insights = []

            cpu_value = cpu.get("value")
            if cpu_value is None:
                insights.append({
                    "type": "cpu_data_missing",
                    "severity": "low",
                    "message": "No recent CPU utilization datapoint is available.",
                    "recommendation": "Verify CloudWatch monitoring and confirm that the instance is reporting metrics.",
                })
            elif cpu_value >= 80:
                insights.append({
                    "type": "high_cpu_utilization",
                    "severity": "high",
                    "message": "EC2 instance CPU utilization is 80% or higher.",
                    "recommendation": "Investigate CPU-intensive workloads and consider scaling or workload optimization.",
                })
            elif cpu_value >= 60:
                insights.append({
                    "type": "elevated_cpu_utilization",
                    "severity": "medium",
                    "message": "EC2 instance CPU utilization is elevated.",
                    "recommendation": "Review recent workload changes and monitor CPU usage for sustained growth.",
                })

            state = instance_status.get("state")
            if state is not None and state != "running":
                insights.append({
                    "type": "instance_not_running",
                    "severity": "low",
                    "message": f"EC2 instance is currently {state}.",
                    "recommendation": "Confirm that the current instance state is expected for this workload.",
                })

            instance_check = instance_status.get("instance_status")
            if instance_check is not None and instance_check != "ok":
                insights.append({
                    "type": "instance_status_issue",
                    "severity": "high",
                    "message": f"EC2 instance status check is {instance_check}.",
                    "recommendation": "Investigate the instance status check failure and review AWS system or instance events.",
                })

            system_check = instance_status.get("system_status")
            if system_check is not None and system_check != "ok":
                insights.append({
                    "type": "system_status_issue",
                    "severity": "high",
                    "message": f"EC2 system status check is {system_check}.",
                    "recommendation": "Investigate the underlying host or AWS infrastructure status affecting the instance.",
                })

            if (
                network.get("metrics", {}).get("NetworkIn") is None
                or network.get("metrics", {}).get("NetworkOut") is None
            ):
                insights.append({
                    "type": "network_data_missing",
                    "severity": "low",
                    "message": "One or more recent network utilization datapoints are unavailable.",
                    "recommendation": "Verify CloudWatch network metric reporting for the instance.",
                })

            health = "warning" if insights else "healthy"

            return {
                "service": "ec2",
                "status": "healthy",
                "instance_id": instance_id,
                "health": health,
                "insight_count": len(insights),
                "insights": insights,
                "cpu": cpu,
                "network": network,
                "instance_status": instance_status,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
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