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
                        "public_ip": instance.get("PublicIpAddress"),
                        "security_groups": [
                            group.get("GroupId")
                            for group in instance.get("SecurityGroups", [])
                            if group.get("GroupId")
                        ],
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

    def get_ec2_efficiency_insights(self):
        try:
            inventory = self.get_ec2_instances()

            if inventory["status"] != "healthy":
                return inventory

            instances = inventory.get("instances", [])
            insights = []

            for instance in instances:
                instance_id = instance.get("instance_id")
                state = instance.get("state")
                instance_name = instance.get("name")

                if state in {"stopped", "stopping"}:
                    insights.append({
                        "type": "stopped_instance",
                        "severity": "medium",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "message": f"EC2 instance is currently {state}.",
                        "recommendation": "Confirm the instance is intentionally stopped and remove it if it is no longer required.",
                    })
                    continue

                if state != "running":
                    continue

                cpu = self.get_ec2_cpu_utilization(instance_id)

                if cpu["status"] != "healthy":
                    continue

                cpu_value = cpu.get("value")

                if cpu_value is not None and cpu_value < 10:
                    insights.append({
                        "type": "low_cpu_utilization",
                        "severity": "low",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "message": "EC2 instance CPU utilization is below 10%.",
                        "recommendation": "Review workload demand and consider rightsizing or scheduling the instance if low usage is sustained.",
                    })

            return {
                "service": "ec2",
                "status": "healthy",
                "health": "warning" if insights else "healthy",
                "insight_count": len(insights),
                "insights": insights,
                "instance_count": len(instances),
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }


    def get_ec2_cost_insights(self):
        try:
            efficiency = self.get_ec2_efficiency_insights()

            if efficiency["status"] != "healthy":
                return efficiency

            cost_insights = []

            for insight in efficiency.get("insights", []):
                insight_type = insight.get("type")

                if insight_type == "stopped_instance":
                    cost_insights.append({
                        "type": "stopped_instance_cost_risk",
                        "severity": "medium",
                        "instance_id": insight.get("instance_id"),
                        "instance_name": insight.get("instance_name"),
                        "message": "A stopped EC2 instance may represent an avoidable resource cost if it is no longer required.",
                        "recommendation": "Confirm the instance is intentionally retained; terminate unused instances and review associated EBS resources when appropriate.",
                    })
                elif insight_type == "low_cpu_utilization":
                    cost_insights.append({
                        "type": "underutilized_instance_cost_risk",
                        "severity": "low",
                        "instance_id": insight.get("instance_id"),
                        "instance_name": insight.get("instance_name"),
                        "message": "EC2 instance CPU utilization is below 10%, indicating possible overprovisioning.",
                        "recommendation": "Review sustained workload demand and consider rightsizing or scheduling the instance to reduce unnecessary compute usage.",
                    })

            return {
                "service": "ec2",
                "status": "healthy",
                "health": "warning" if cost_insights else "healthy",
                "insight_count": len(cost_insights),
                "insights": cost_insights,
                "instance_count": efficiency.get("instance_count", 0),
                "note": "Cost insights are qualitative; actual AWS charges require billing and pricing data.",
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_ec2_rightsizing_insights(self):
        try:
            inventory = self.get_ec2_instances()

            if inventory["status"] != "healthy":
                return inventory

            instances = inventory.get("instances", [])
            insights = []

            for instance in instances:
                instance_id = instance.get("instance_id")
                instance_name = instance.get("name")
                instance_type = instance.get("instance_type")
                state = instance.get("state")

                if state in {"stopped", "stopping"}:
                    insights.append({
                        "type": "stopped_instance_lifecycle",
                        "severity": "medium",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "message": f"EC2 instance is currently {state} and cannot be evaluated for active right-sizing.",
                        "recommendation": "Confirm the instance is intentionally retained and remove it if it is no longer required.",
                    })
                    continue

                if state != "running":
                    continue

                cpu = self.get_ec2_cpu_utilization(instance_id)

                if cpu["status"] != "healthy":
                    continue

                cpu_value = cpu.get("value")

                if cpu_value is None:
                    insights.append({
                        "type": "insufficient_cpu_data",
                        "severity": "low",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "message": "Recent CPU utilization data is unavailable for right-sizing evaluation.",
                        "recommendation": "Wait for CloudWatch CPU metrics and evaluate sustained utilization before changing the instance size.",
                    })
                elif cpu_value < 10:
                    insights.append({
                        "type": "consider_downsizing",
                        "severity": "low",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "cpu_utilization": cpu_value,
                        "message": "EC2 instance CPU utilization is below 10%.",
                        "recommendation": "Review sustained workload demand and consider moving to a smaller instance type if capacity remains sufficient.",
                    })
                elif cpu_value >= 60:
                    insights.append({
                        "type": "avoid_downsizing",
                        "severity": "medium",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "cpu_utilization": cpu_value,
                        "message": "EC2 instance CPU utilization is 60% or higher.",
                        "recommendation": "Avoid downsizing based on CPU alone and review workload demand before reducing capacity.",
                    })

            return {
                "service": "ec2",
                "status": "healthy",
                "health": "warning" if insights else "healthy",
                "insight_count": len(insights),
                "insights": insights,
                "instance_count": len(instances),
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_ec2_security_insights(self):
        try:
            inventory = self.get_ec2_instances()

            if inventory["status"] != "healthy":
                return inventory

            instances = inventory.get("instances", [])
            insights = []

            for instance in instances:
                instance_id = instance.get("instance_id")
                instance_name = instance.get("name")
                instance_type = instance.get("instance_type")
                state = instance.get("state")
                public_ip = instance.get("public_ip")
                security_groups = instance.get("security_groups", [])

                if state in {"terminated", "shutting-down"}:
                    continue

                if public_ip:
                    insights.append({
                        "type": "public_ip_exposure",
                        "severity": "medium",
                        "instance_id": instance_id,
                        "instance_name": instance_name,
                        "instance_type": instance_type,
                        "public_ip": public_ip,
                        "security_group_count": len(security_groups),
                        "message": "EC2 instance has a public IPv4 address and is potentially reachable from the internet.",
                        "recommendation": "Confirm public exposure is required and review security group and network access controls for the instance.",
                    })

            return {
                "service": "ec2",
                "status": "healthy",
                "health": "warning" if insights else "healthy",
                "insight_count": len(insights),
                "insights": insights,
                "instance_count": len(instances),
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "ec2",
                "status": "unhealthy",
                "error": str(error),
            }

    def get_s3_security_insights(self, bucket_name):
        try:
            s3 = boto3.client("s3")

            insights = []
            configuration = {
                "encryption": None,
                "public_access_block": None,
            }
            unavailable_checks = []

            try:
                encryption_response = s3.get_bucket_encryption(
                    Bucket=bucket_name,
                )

                rules = encryption_response.get("ServerSideEncryptionConfiguration", {}).get(
                    "Rules",
                    [],
                )

                if rules:
                    default_encryption = rules[0].get("ApplyServerSideEncryptionByDefault", {})
                    configuration["encryption"] = {
                        "algorithm": default_encryption.get("SSEAlgorithm"),
                        "kms_key_id": default_encryption.get("KMSMasterKeyID"),
                    }

                if not configuration["encryption"] or not configuration["encryption"].get("algorithm"):
                    insights.append({
                        "type": "encryption_not_configured",
                        "severity": "medium",
                        "message": "Bucket default server-side encryption configuration was not detected.",
                        "recommendation": "Review the bucket encryption configuration and enable default server-side encryption where appropriate.",
                    })

            except ClientError as error:
                error_code = error.response.get("Error", {}).get("Code")
                if error_code in {"AccessDenied", "AllAccessDisabled"}:
                    unavailable_checks.append("encryption")
                elif error_code in {"ServerSideEncryptionConfigurationNotFoundError", "NoSuchBucket"}:
                    if error_code == "ServerSideEncryptionConfigurationNotFoundError":
                        insights.append({
                            "type": "encryption_not_configured",
                            "severity": "medium",
                            "message": "Bucket does not have a default server-side encryption configuration.",
                            "recommendation": "Enable default server-side encryption for new objects where appropriate.",
                        })
                    else:
                        raise
                else:
                    raise

            try:
                public_access_response = s3.get_public_access_block(
                    Bucket=bucket_name,
                )

                public_access = public_access_response.get("PublicAccessBlockConfiguration", {})
                configuration["public_access_block"] = public_access

                required_flags = {
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                }

                missing_flags = [
                    flag for flag in required_flags
                    if public_access.get(flag) is not True
                ]

                if missing_flags:
                    insights.append({
                        "type": "public_access_protection_incomplete",
                        "severity": "high",
                        "message": "S3 Public Access Block is not fully enabled for the bucket.",
                        "missing_controls": sorted(missing_flags),
                        "recommendation": "Review whether public access is required and enable all Public Access Block controls when public access is not needed.",
                    })

            except ClientError as error:
                error_code = error.response.get("Error", {}).get("Code")
                if error_code in {"AccessDenied", "AllAccessDisabled"}:
                    unavailable_checks.append("public_access_block")
                elif error_code == "NoSuchPublicAccessBlockConfiguration":
                    insights.append({
                        "type": "public_access_protection_missing",
                        "severity": "high",
                        "message": "Bucket has no Public Access Block configuration detected.",
                        "recommendation": "Review whether public access is required and configure S3 Public Access Block when it is not needed.",
                    })
                else:
                    raise

            if unavailable_checks:
                insights.append({
                    "type": "security_configuration_unavailable",
                    "severity": "low",
                    "message": "Some S3 security configuration checks could not be read with the current AWS permissions.",
                    "checks": sorted(unavailable_checks),
                    "recommendation": "Grant the minimum required read permissions if these security checks are needed by CloudOps AI.",
                })

            health = "warning" if any(
                insight["severity"] in {"high", "medium"}
                for insight in insights
            ) else ("unknown" if unavailable_checks else "healthy")

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "health": health,
                "insight_count": len(insights),
                "insights": insights,
                "configuration": configuration,
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
                "error": str(error),
            }

    def get_s3_cost_insights(self, bucket_name, prefix=None, max_keys=None):
        try:
            storage = self.get_s3_largest_objects(
                bucket_name,
                prefix=prefix,
                max_keys=max_keys,
                top_n=1,
            )

            if storage["status"] != "healthy":
                return storage

            insights = []
            total_objects = storage.get("total_objects", 0)
            total_size_bytes = storage.get("total_size_bytes", 0)
            average_object_size_bytes = storage.get("average_object_size_bytes", 0)
            largest_object = storage.get("largest_object")

            if total_objects == 0:
                insights.append({
                    "type": "empty_bucket_cost_opportunity",
                    "severity": "low",
                    "message": "Bucket contains no objects and may not be contributing useful storage value.",
                    "recommendation": "Review whether the bucket is still required and remove unused buckets when appropriate.",
                })

            if total_size_bytes >= 100 * 1024 * 1024 * 1024:
                insights.append({
                    "type": "large_storage_cost_risk",
                    "severity": "medium",
                    "total_size_bytes": total_size_bytes,
                    "message": "Bucket has a large storage footprint that may contribute materially to storage charges.",
                    "recommendation": "Review retention, lifecycle, storage classes, and stale data to identify cost optimization opportunities.",
                })

            if total_objects >= 100000:
                insights.append({
                    "type": "high_object_count_cost_risk",
                    "severity": "medium",
                    "total_objects": total_objects,
                    "message": "Bucket contains a very large number of objects, which can increase request and management overhead.",
                    "recommendation": "Review object lifecycle, retention, and object layout to reduce unnecessary object and request overhead.",
                })

            if total_objects >= 1000 and average_object_size_bytes <= 128 * 1024:
                insights.append({
                    "type": "small_object_cost_optimization",
                    "severity": "low",
                    "total_objects": total_objects,
                    "average_object_size_bytes": average_object_size_bytes,
                    "message": "Bucket contains many relatively small objects, which may increase request and metadata overhead.",
                    "recommendation": "Review whether objects can be aggregated or lifecycle-managed more efficiently where application requirements allow.",
                })

            if largest_object and largest_object.get("size", 0) >= 5 * 1024 * 1024 * 1024:
                insights.append({
                    "type": "very_large_object_cost_opportunity",
                    "severity": "low",
                    "largest_object": largest_object,
                    "message": "Bucket contains a very large object that may benefit from storage-class or lifecycle review.",
                    "recommendation": "Review access frequency and retention for the largest object and consider an appropriate storage class or lifecycle policy.",
                })

            return {
                "service": "s3",
                "status": "healthy",
                "bucket": bucket_name,
                "prefix": prefix,
                "health": "warning" if insights else "healthy",
                "insight_count": len(insights),
                "insights": insights,
                "total_objects": total_objects,
                "total_size_bytes": total_size_bytes,
                "average_object_size_bytes": average_object_size_bytes,
                "largest_object": largest_object,
                "note": "Cost insights are qualitative; actual AWS charges require billing and pricing data.",
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "service": "s3",
                "status": "unhealthy",
                "bucket": bucket_name,
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