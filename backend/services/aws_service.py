import boto3
from botocore.exceptions import BotoCoreError, ClientError


class AWSService:
    def get_status(self):
        try:
            sts = boto3.client("sts")
            identity = sts.get_caller_identity()

            return {
                "provider": "AWS",
                "status": "connected",
                "account_id": identity.get("Account"),
                "arn": identity.get("Arn"),
                "services": {
                    "sts": "healthy",
                },
                "message": "AWS connection is working",
            }

        except (BotoCoreError, ClientError) as error:
            return {
                "provider": "AWS",
                "status": "disconnected",
                "message": "Unable to connect to AWS",
                "error": str(error),
            }

    def get_service_health(self, service_name):
        if service_name == "sts":
            try:
                sts = boto3.client("sts")
                sts.get_caller_identity()
                return {"service": "sts", "status": "healthy"}
            except (BotoCoreError, ClientError) as error:
                return {
                    "service": "sts",
                    "status": "unhealthy",
                    "error": str(error),
                }

        return {
            "service": service_name,
            "status": "unsupported",
            "message": "Service health check is not supported yet",
        }