from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import json

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





def test_tenant_role_mapping_supports_sts_external_id(monkeypatch):
    class FakeSession:
        def client(self, name, **kwargs):
            return name

    class FakeSts:
        calls = []

        def assume_role(self, **kwargs):
            self.calls.append(kwargs)
            return {"Credentials": {
                "AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    sts = FakeSts()
    mapping = {
        "tenant-a": {
            "role_arn": "arn:aws:iam::123456789012:role/tenant-a",
            "external_id": "cloudops-tenant-a-external",
        }
    }
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", json.dumps(mapping))
    monkeypatch.setattr(aws_service.boto3, "client", lambda *_args, **_kwargs: sts)
    monkeypatch.setattr(aws_service.boto3, "Session", lambda **_kwargs: FakeSession())
    aws_service._assumed_sessions.pop("tenant-a", None)
    token = aws_service.set_aws_tenant("tenant-a")
    try:
        aws_service._aws_client("ec2")
        assert sts.calls[0]["ExternalId"] == "cloudops-tenant-a-external"
        assert sts.calls[0]["RoleArn"] == mapping["tenant-a"]["role_arn"]
    finally:
        aws_service.reset_aws_tenant(token)
        aws_service._assumed_sessions.pop("tenant-a", None)


def test_external_id_change_invalidates_cached_tenant_session(monkeypatch):
    class FakeSession:
        def client(self, name, **kwargs):
            return name

    class FakeSts:
        calls = []

        def assume_role(self, **kwargs):
            self.calls.append(kwargs.copy())
            return {"Credentials": {
                "AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    sts = FakeSts()
    monkeypatch.setattr(aws_service.boto3, "client", lambda *_args, **_kwargs: sts)
    monkeypatch.setattr(aws_service.boto3, "Session", lambda **_kwargs: FakeSession())
    aws_service._assumed_sessions.pop("tenant-a", None)
    token = aws_service.set_aws_tenant("tenant-a")
    try:
        for external_id in ("external-v1", "external-v2"):
            monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", json.dumps({
                "tenant-a": {
                    "role_arn": "arn:aws:iam::123456789012:role/tenant-a",
                    "external_id": external_id,
                }
            }))
            aws_service._aws_client("ec2")
    finally:
        aws_service.reset_aws_tenant(token)
        aws_service._assumed_sessions.pop("tenant-a", None)

    assert [call["ExternalId"] for call in sts.calls] == ["external-v1", "external-v2"]


@pytest.mark.parametrize("mapping", [
    {"tenant-a": "arn:aws:s3:::not-a-role"},
    {"tenant-a": "arn:aws:iam::123:role/short-account"},
    {"tenant-a": {"role_arn": "arn:aws:iam::123456789012:role/tenant-a", "external_id": ""}},
    {"tenant-a": {"role_arn": "arn:aws:iam::123456789012:role/tenant-a", "external_id": "bad value"}},
    {"tenant-a": {"role_arn": "arn:aws:iam::123456789012:role/tenant-a", "external_id": "valid", "extra": "field"}},
])
def test_tenant_role_mapping_rejects_invalid_role_arns_and_external_ids(monkeypatch, mapping):
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", json.dumps(mapping))
    with pytest.raises(RuntimeError):
        aws_service._tenant_role_config("tenant-a")


def test_unmapped_tenant_keeps_default_aws_identity(monkeypatch):
    sentinel = object()
    monkeypatch.setenv("CLOUDOPS_ENV", "development")
    monkeypatch.delenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", raising=False)
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", "{}")
    monkeypatch.setattr(aws_service.boto3, "client", lambda *args, **kwargs: sentinel)
    token = aws_service.set_aws_tenant("tenant-without-role")
    try:
        assert aws_service._aws_client("ec2") is sentinel
    finally:
        aws_service.reset_aws_tenant(token)


def test_production_requires_tenant_role_by_default(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_ENV", "production")
    monkeypatch.delenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", raising=False)
    assert aws_service._tenant_roles_required()


def test_explicit_tenant_role_setting_overrides_environment_default(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_ENV", "production")
    monkeypatch.setenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", "false")
    assert not aws_service._tenant_roles_required()
    monkeypatch.setenv("CLOUDOPS_ENV", "development")
    monkeypatch.setenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", "true")
    assert aws_service._tenant_roles_required()


def test_required_tenant_role_fails_closed_without_using_process_identity(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", "{}")
    monkeypatch.setenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", "true")
    monkeypatch.setattr(
        aws_service.boto3, "client",
        lambda *_args, **_kwargs: pytest.fail("shared AWS identity must not be used"),
    )
    token = aws_service.set_aws_tenant("tenant-without-role")
    try:
        with pytest.raises(RuntimeError, match="No AWS role is configured"):
            aws_service._aws_client("ec2")
    finally:
        aws_service.reset_aws_tenant(token)


@pytest.mark.parametrize("setting", ["yes", "1", "", "sometimes"])
def test_required_tenant_role_setting_rejects_ambiguous_values(monkeypatch, setting):
    monkeypatch.setenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", setting)
    with pytest.raises(RuntimeError, match="must be true or false"):
        aws_service._tenant_roles_required()


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



def test_tenant_role_cache_refreshes_when_role_mapping_changes(monkeypatch):
    class FakeSession:
        def __init__(self, role):
            self.role = role

        def client(self, name, **kwargs):
            return (self.role, name, kwargs)

    class FakeSts:
        roles = []

        def assume_role(self, **kwargs):
            self.roles.append(kwargs["RoleArn"])
            return {"Credentials": {
                "AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    sts = FakeSts()
    sessions = []
    monkeypatch.setattr(aws_service.boto3, "client", lambda *_args, **_kwargs: sts)

    def make_session(**kwargs):
        session = FakeSession(kwargs["aws_access_key_id"])
        sessions.append(session)
        return session

    monkeypatch.setattr(aws_service.boto3, "Session", make_session)
    aws_service._assumed_sessions.pop("tenant-a", None)
    token = aws_service.set_aws_tenant("tenant-a")
    try:
        monkeypatch.setenv(
            "CLOUDOPS_TENANT_AWS_ROLES",
            '{"tenant-a":"arn:aws:iam::123456789012:role/tenant-a-v1"}',
        )
        first = aws_service._aws_client("ec2")
        monkeypatch.setenv(
            "CLOUDOPS_TENANT_AWS_ROLES",
            '{"tenant-a":"arn:aws:iam::123456789012:role/tenant-a-v2"}',
        )
        second = aws_service._aws_client("s3")
    finally:
        aws_service.reset_aws_tenant(token)
        aws_service._assumed_sessions.pop("tenant-a", None)

    assert first[0] == "key"
    assert second[0] == "key"
    assert len(sessions) == 2
    assert sts.roles == [
        "arn:aws:iam::123456789012:role/tenant-a-v1",
        "arn:aws:iam::123456789012:role/tenant-a-v2",
    ]


def test_tenant_role_cache_evicts_least_recently_used_entries(monkeypatch):
    class FakeSession:
        def client(self, name, **kwargs):
            return name

    class FakeSts:
        calls = 0

        def assume_role(self, **kwargs):
            self.calls += 1
            return {"Credentials": {
                "AccessKeyId": "key", "SecretAccessKey": "secret", "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    sts = FakeSts()
    monkeypatch.setattr(aws_service.boto3, "client", lambda *_args, **_kwargs: sts)
    monkeypatch.setattr(aws_service.boto3, "Session", lambda **_kwargs: FakeSession())
    monkeypatch.setattr(aws_service, "_ASSUMED_SESSION_CACHE_MAX_ENTRIES", 2)
    aws_service._assumed_sessions.clear()
    monkeypatch.setenv(
        "CLOUDOPS_TENANT_AWS_ROLES",
        '{"tenant-a":"arn:aws:iam::123456789012:role/a",'
        '"tenant-b":"arn:aws:iam::123456789012:role/b",'
        '"tenant-c":"arn:aws:iam::123456789012:role/c"}',
    )
    try:
        for tenant in ("tenant-a", "tenant-b", "tenant-a", "tenant-c"):
            token = aws_service.set_aws_tenant(tenant)
            try:
                aws_service._aws_client("ec2")
            finally:
                aws_service.reset_aws_tenant(token)

        assert list(aws_service._assumed_sessions) == ["tenant-a", "tenant-c"]
        token = aws_service.set_aws_tenant("tenant-b")
        try:
            aws_service._aws_client("ec2")
        finally:
            aws_service.reset_aws_tenant(token)
        assert sts.calls == 4
        assert len(aws_service._assumed_sessions) == 2
    finally:
        aws_service._assumed_sessions.clear()



def test_removed_tenant_role_mapping_discards_cached_session(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_REQUIRE_TENANT_AWS_ROLE", "false")
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", "{}")
    aws_service._assumed_sessions["tenant-revoked"] = (
        datetime.now(timezone.utc).timestamp() + 3600,
        "arn:aws:iam::123456789012:role/old",
        object(),
    )
    try:
        assert aws_service._tenant_session("tenant-revoked") is None
        assert "tenant-revoked" not in aws_service._assumed_sessions
    finally:
        aws_service._assumed_sessions.pop("tenant-revoked", None)

def test_different_tenants_refresh_sts_sessions_concurrently(monkeypatch):
    # Select tenant IDs that map to different fixed lock stripes.
    tenants_by_stripe = {}
    for index in range(1000):
        tenant_id = f"tenant-{index}"
        stripe = hash(tenant_id) % len(aws_service._TENANT_SESSION_LOCKS)
        tenants_by_stripe.setdefault(stripe, tenant_id)
        if len(tenants_by_stripe) == 2:
            break
    tenant_ids = list(tenants_by_stripe.values())
    roles = {
        tenant_id: f"arn:aws:iam::123456789012:role/{tenant_id}"
        for tenant_id in tenant_ids
    }
    monkeypatch.setenv("CLOUDOPS_TENANT_AWS_ROLES", json.dumps(roles))
    barrier = Barrier(2)

    class FakeSts:
        def assume_role(self, **kwargs):
            # Both tenant refreshes must reach STS before either can finish.
            barrier.wait(timeout=5)
            return {"Credentials": {
                "AccessKeyId": kwargs["RoleArn"],
                "SecretAccessKey": "secret",
                "SessionToken": "session",
                "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            }}

    class FakeSession:
        pass

    monkeypatch.setattr(aws_service.boto3, "client", lambda *_args, **_kwargs: FakeSts())
    monkeypatch.setattr(aws_service.boto3, "Session", lambda **_kwargs: FakeSession())
    for tenant_id in tenant_ids:
        aws_service._assumed_sessions.pop(tenant_id, None)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            sessions = list(executor.map(aws_service._tenant_session, tenant_ids))

        assert all(isinstance(session, FakeSession) for session in sessions)
        assert all(tenant_id in aws_service._assumed_sessions for tenant_id in tenant_ids)
    finally:
        for tenant_id in tenant_ids:
            aws_service._assumed_sessions.pop(tenant_id, None)

