from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

import main
from services.aws_service import AWSService
from auth import AccessControlMiddleware, Principal


INSTANCE = "i-12345678"


def test_instance_security_groups_returns_ingress_details(monkeypatch):
    expected = {
        "service": "ec2", "status": "healthy", "instance_id": INSTANCE,
        "security_groups": [{
            "group_id": "sg-12345678", "group_name": "web", "description": "web access",
            "vpc_id": "vpc-12345678", "ingress_rules": [{
                "protocol": "tcp", "from_port": 443, "to_port": 443,
                "ipv4_ranges": [{"cidr": "0.0.0.0/0", "description": "public HTTPS"}],
                "ipv6_ranges": [], "prefix_list_ids": [], "source_security_groups": [],
            }], "egress_rules": [],
        }],
    }
    calls = []
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_security_groups", lambda instance_id, **kwargs: calls.append((instance_id, kwargs)) or expected)

    response = TestClient(main.app).get(f"/cloud/aws/ec2/instances/{INSTANCE}/security-groups?region=us-east-1")

    assert response.status_code == 200
    assert response.json() == expected
    assert calls == [(INSTANCE, {"region": "us-east-1"})]


def test_instance_security_groups_rejects_malformed_and_unhealthy_results(monkeypatch):
    for payload in (
        {"service": "ec2", "status": "healthy", "instance_id": INSTANCE, "security_groups": [{"group_id": "sg-1", "ingress_rules": [{"protocol": "tcp", "ipv4_ranges": [{"cidr": 42}], "ipv6_ranges": [], "prefix_list_ids": [], "source_security_groups": []}]}]},
        {"service": "ec2", "status": "healthy", "instance_id": INSTANCE, "security_groups": "bad"},
        {"service": "ec2", "status": "healthy", "instance_id": INSTANCE, "security_groups": [{"group_id": "sg-1", "ingress_rules": [], "egress_rules": [{"protocol": "tcp", "ipv4_ranges": "bad", "ipv6_ranges": [], "prefix_list_ids": [], "source_security_groups": []}]}]},
        {"service": "ec2", "status": "unhealthy", "error": "secret"},
    ):
        monkeypatch.setattr(main.aws_service, "get_ec2_instance_security_groups", lambda *a, _payload=payload, **k: _payload)
        response = TestClient(main.app).get(f"/cloud/aws/ec2/instances/{INSTANCE}/security-groups")
        assert response.status_code == 503
        assert response.json() == {"detail": "AWS resource data is unavailable"}
        assert "secret" not in response.text


def test_instance_security_groups_validates_region_before_provider(monkeypatch):
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_security_groups", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider called")))

    response = TestClient(main.app).get(f"/cloud/aws/ec2/instances/{INSTANCE}/security-groups?region=not-a-region")

    assert response.status_code == 400


def test_security_group_egress_is_tenant_scoped_and_requires_authentication(monkeypatch):
    app = FastAPI()
    app.router.routes.extend(main.app.router.routes)
    app.add_middleware(AccessControlMiddleware, mode="token", tokens={
        "reader": Principal("alice", "reader", "tenant-a"),
    })
    client = TestClient(app)
    monkeypatch.setattr(main.aws_service, "get_ec2_instance", lambda instance_id, **kwargs: {
        "status": "healthy", "instance": {"instance_id": instance_id, "tags": {
            "CloudOpsTenantId": "tenant-a" if instance_id == "i-aaaaaaaa" else "tenant-b",
        }},
    })
    calls = []
    monkeypatch.setattr(main.aws_service, "get_ec2_instance_security_groups", lambda instance_id, **kwargs: calls.append(instance_id) or {
        "service": "ec2", "status": "healthy", "instance_id": instance_id,
        "security_groups": [{"group_id": "sg-12345678", "ingress_rules": [], "egress_rules": [
            {"protocol": "-1", "from_port": None, "to_port": None, "ipv4_ranges": [{"cidr": "0.0.0.0/0", "description": None}], "ipv6_ranges": [], "prefix_list_ids": [], "destination_security_groups": []},
        ]}],
    })

    unauthenticated = client.get(f"/cloud/aws/ec2/instances/{INSTANCE}/security-groups")
    owned = client.get("/cloud/aws/ec2/instances/i-aaaaaaaa/security-groups", headers={"Authorization": "Bearer reader"})
    foreign = client.get("/cloud/aws/ec2/instances/i-bbbbbbbb/security-groups", headers={"Authorization": "Bearer reader"})

    assert unauthenticated.status_code == 401
    assert owned.status_code == 200
    assert owned.json()["security_groups"][0]["egress_rules"][0]["ipv4_ranges"][0]["cidr"] == "0.0.0.0/0"
    assert foreign.status_code == 404
    assert calls == ["i-aaaaaaaa"]


def test_provider_maps_instance_groups_and_all_ingress_source_types(monkeypatch):
    class Client:
        def describe_instances(self, **kwargs):
            assert kwargs == {"InstanceIds": [INSTANCE]}
            return {"Reservations": [{"Instances": [{"SecurityGroups": [{"GroupId": "sg-12345678"}]}]}]}

        def describe_security_groups(self, **kwargs):
            assert kwargs == {"GroupIds": ["sg-12345678"]}
            return {"SecurityGroups": [{
                "GroupId": "sg-12345678", "GroupName": "web", "Description": "web",
                "VpcId": "vpc-12345678", "IpPermissions": [{
                    "IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    "Ipv6Ranges": [{"CidrIpv6": "::/0"}], "PrefixListIds": [{"PrefixListId": "pl-12345678"}],
                    "UserIdGroupPairs": [{"GroupId": "sg-87654321", "UserId": "123456789012", "VpcId": "vpc-12345678"}],
                }], "IpPermissionsEgress": [{
                    "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                    "IpRanges": [{"CidrIp": "10.0.0.0/8", "Description": "internal egress"}],
                    "UserIdGroupPairs": [{"GroupId": "sg-11111111", "UserId": "123456789012", "VpcId": "vpc-12345678"}],
                }],
            }]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: Client())

    result = AWSService().get_ec2_instance_security_groups(INSTANCE, region="us-east-1")

    rule = result["security_groups"][0]["ingress_rules"][0]
    assert result["status"] == "healthy"
    assert rule["protocol"] == "-1"
    assert rule["ipv6_ranges"] == [{"cidr": "::/0", "description": None}]
    assert rule["prefix_list_ids"] == ["pl-12345678"]
    assert rule["source_security_groups"] == [{"group_id": "sg-87654321", "owner_id": "123456789012", "vpc_id": "vpc-12345678"}]
    egress = result["security_groups"][0]["egress_rules"][0]
    assert egress == {
        "protocol": "tcp", "from_port": 443, "to_port": 443,
        "ipv4_ranges": [{"cidr": "10.0.0.0/8", "description": "internal egress"}],
        "ipv6_ranges": [], "prefix_list_ids": [], "destination_security_groups": [{"group_id": "sg-11111111", "owner_id": "123456789012", "vpc_id": "vpc-12345678"}],
    }


def test_provider_returns_explicit_empty_groups_and_sanitizable_failure(monkeypatch):
    class EmptyClient:
        def describe_instances(self, **kwargs):
            return {"Reservations": [{"Instances": [{"SecurityGroups": []}]}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: EmptyClient())
    service = AWSService()
    assert service.get_ec2_instance_security_groups(INSTANCE)["security_groups"] == []

    class MalformedClient:
        def describe_instances(self, **kwargs):
            return {"Reservations": [{"Instances": [{"SecurityGroups": [{"GroupId": "sg-12345678"}]}]}]}

        def describe_security_groups(self, **kwargs):
            return {"SecurityGroups": [{"GroupId": "sg-12345678", "IpPermissions": [{"IpRanges": "not-a-list"}]}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: MalformedClient())
    assert service.get_ec2_instance_security_groups(INSTANCE)["status"] == "unhealthy"

    class MalformedEgressClient:
        def describe_instances(self, **kwargs):
            return {"Reservations": [{"Instances": [{"SecurityGroups": [{"GroupId": "sg-12345678"}]}]}]}

        def describe_security_groups(self, **kwargs):
            return {"SecurityGroups": [{"GroupId": "sg-12345678", "IpPermissions": [], "IpPermissionsEgress": "invalid"}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: MalformedEgressClient())
    assert service.get_ec2_instance_security_groups(INSTANCE)["status"] == "unhealthy"

    class MissingEgressClient:
        def describe_instances(self, **kwargs):
            return {"Reservations": [{"Instances": [{"SecurityGroups": [{"GroupId": "sg-12345678"}]}]}]}

        def describe_security_groups(self, **kwargs):
            return {"SecurityGroups": [{"GroupId": "sg-12345678", "IpPermissions": []}]}

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: MissingEgressClient())
    assert service.get_ec2_instance_security_groups(INSTANCE)["status"] == "unhealthy"

    class BrokenClient:
        def describe_instances(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private details"}}, "DescribeInstances")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: BrokenClient())
    assert service.get_ec2_instance_security_groups(INSTANCE)["status"] == "unhealthy"


def test_console_labels_and_renders_both_security_group_directions():
    html = TestClient(main.app).get("/console").text

    assert "Security group rules" in html
    assert "ingress_rules" in html
    assert "egress_rules" in html
    assert "No ${label.toLowerCase()} rules." in html
    assert "Outbound" in html
