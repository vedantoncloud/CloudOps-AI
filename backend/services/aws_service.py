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