from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

import main
from services.aws_service import AWSService


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
            }],
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

    class BrokenClient:
        def describe_instances(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "private details"}}, "DescribeInstances")

    monkeypatch.setattr("services.aws_service._aws_client", lambda *a, **k: BrokenClient())
    assert service.get_ec2_instance_security_groups(INSTANCE)["status"] == "unhealthy"
