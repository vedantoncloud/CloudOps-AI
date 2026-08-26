import boto3
from botocore.exceptions import BotoCoreError, ClientError


class AWSService:
    def get_status(self):
        try:
            sts = boto3.client("sts")
            identity = sts.get_caller_identity()

            s3 = boto3.client("s3")
            s3.list_buckets()

            return {
                "provider": "AWS",
                "status": "connected",
                "account_id": identity.get("Account"),
                "arn": identity.get("Arn"),
                "services": {
                    "sts": "healthy",
                    "s3": "healthy",
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