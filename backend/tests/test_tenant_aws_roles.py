from datetime import datetime, timedelta, timezone

import pytest

from services import aws_service


def test_tenant_aws_role_uses_cached_assumed_session(monkeypatch):
    class FakeSession:
        def client(self, name, **kwargs):
            return ("tenant-session", name, kwargs)

    class FakeSts:
        calls = 0

        def assume_role(self, **kwargs):
            self.calls += 1
            assert kwargs["RoleArn"] == "arn:aws:iam::123456789012:role/tenant-a"
            return {"Credentials": {
                "AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    sts = FakeSts()
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", '{"tenant-a":"arn:aws:iam::123456789012:role/tenant-a"}')
    monkeypatch.setattr(aws_service.boto3, "client", lambda name, **kwargs: sts)
    monkeypatch.setattr(aws_service.boto3, "Session", lambda **kwargs: FakeSession())
    aws_service._assumed_sessions.pop("tenant-a", None)
    token = aws_service.set_aws_tenant("tenant-a")
    try:
        first = aws_service._aws_client("ec2", region_name="us-west-2")
        second = aws_service._aws_client("s3")
    finally:
        aws_service.reset_aws_tenant(token)

    assert first[0:2] == ("tenant-session", "ec2")
    assert first[2]["region_name"] == "us-west-2"
    assert second[0:2] == ("tenant-session", "s3")
    assert sts.calls == 1
    aws_service._assumed_sessions.pop("tenant-a", None)


def test_tenant_role_configuration_rejects_malformed_or_untrusted_values(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", "[]")
    with pytest.raises(RuntimeError, match="must map tenant IDs"):
        aws_service._tenant_role_arn("tenant-a")
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", '{"tenant-a":"not-an-arn"}')
    with pytest.raises(RuntimeError, match="must map tenant IDs"):
        aws_service._tenant_role_arn("tenant-a")


def test_unmapped_tenant_keeps_default_aws_identity(monkeypatch):
    sentinel = object()
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", "{}")
    monkeypatch.setattr(aws_service.boto3, "client", lambda *args, **kwargs: sentinel)
    token = aws_service.set_aws_tenant("tenant-without-role")
    try:
        assert aws_service._aws_client("ec2") is sentinel
    finally:
        aws_service.reset_aws_tenant(token)


def test_failed_role_assumption_does_not_fall_back_to_shared_credentials(monkeypatch):
    class DeniedSts:
        def assume_role(self, **kwargs):
            raise PermissionError("role trust policy denied access")

    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", '{"tenant-a":"arn:aws:iam::123456789012:role/tenant-a"}')
    monkeypatch.setattr(aws_service.boto3, "client", lambda *args, **kwargs: DeniedSts())
    token = aws_service.set_aws_tenant("tenant-a")
    try:
        with pytest.raises(PermissionError, match="trust policy"):
            aws_service._aws_client("ec2")
    finally:
        aws_service.reset_aws_tenant(token)
