import json
from types import SimpleNamespace
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from services.aws_service import AWSService


POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "ReadReports",
        "Effect": "Allow",
        "Principal": {"AWS": "arn:aws:iam::123456789012:role/reports"},
        "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::archive/reports/*",
        "Condition": {"StringLike": {"aws:PrincipalArn": "*reports*"}},
    }],
}


def test_bucket_policy_returns_parsed_statements_and_handles_absent_policy():
    with patch("services.aws_service.boto3.client") as client:
        s3 = client.return_value
        s3.get_bucket_policy.return_value = {"Policy": json.dumps(POLICY)}
        configured = AWSService().get_s3_bucket_policy("archive")
        s3.get_bucket_policy.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucketPolicy"}}, "GetBucketPolicy"
        )
        absent = AWSService().get_s3_bucket_policy("archive")

    assert configured == {
        "service": "s3", "status": "healthy", "bucket": "archive",
        "configured": True, "policy": POLICY,
    }
    assert absent == {
        "service": "s3", "status": "healthy", "bucket": "archive",
        "configured": False, "policy": None,
    }


def test_bucket_policy_provider_failure_and_malformed_document_fail_closed():
    with patch("services.aws_service.boto3.client") as client:
        s3 = client.return_value
        s3.get_bucket_policy.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private details"}},
            "GetBucketPolicy",
        )
        failed = AWSService().get_s3_bucket_policy("archive")
        s3.get_bucket_policy.side_effect = None
        s3.get_bucket_policy.return_value = {"Policy": '{"Statement":"invalid"}'}
        malformed = AWSService().get_s3_bucket_policy("archive")

    assert failed["status"] == "unhealthy"
    assert malformed == {
        "service": "s3", "status": "unhealthy", "bucket": "archive"
    }


def test_policy_endpoint_is_tenant_scoped_and_sanitizes_provider_failure(monkeypatch):
    class StubAWS:
        owner = "tenant-a"
        fail = False

        def get_s3_bucket_tags(self, bucket):
            return {"status": "healthy", "tags": {"CloudOpsTenantId": self.owner}}

        def get_s3_bucket_policy(self, bucket):
            if self.fail:
                return {"status": "unhealthy", "error": "private provider detail"}
            return {"status": "healthy", "configured": True, "policy": POLICY}

    stub = StubAWS()
    monkeypatch.setattr(main, "aws_service", stub)
    client = TestClient(main.app)
    response = client.get("/cloud/aws/s3/buckets/archive/policy")
    assert response.status_code == 200
    assert response.json()["policy"] == POLICY

    stub.fail = True
    response = client.get("/cloud/aws/s3/buckets/archive/policy")
    assert response.status_code == 503
    assert "private provider detail" not in response.text

    stub.owner = "tenant-b"
    request = SimpleNamespace(state=SimpleNamespace(tenant_scoped=True, tenant_id="tenant-a"))
    try:
        main.aws_s3_bucket_policy("archive", request)
        assert False, "foreign buckets must be hidden"
    except HTTPException as error:
        assert error.status_code == 404


def test_bucket_policy_is_in_console_analysis():
    html = TestClient(main.app).get("/console").text
    assert "['Bucket policy',`${base}/policy`]" in html
