import boto3
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