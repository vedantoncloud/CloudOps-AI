from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from services.aws_service import AWSService


def test_instance_volumes_report_encryption_and_only_matching_attachment():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{
        "BlockDeviceMappings": [
            {"Ebs": {"VolumeId": "vol-b"}},
            {"Ebs": {"VolumeId": "vol-a"}},
            {"DeviceName": "/dev/sda1"},
        ]
    }]}]}
    ec2.describe_volumes.return_value = {"Volumes": [
        {"VolumeId": "vol-a", "Encrypted": True, "KmsKeyId": "key-1", "Size": 20,
         "VolumeType": "gp3", "State": "in-use", "Attachments": [
             {"InstanceId": "i-12345678", "Device": "/dev/sda1", "State": "attached"},
             {"InstanceId": "i-other", "Device": "/dev/sdf", "State": "attached"},
         ]},
        {"VolumeId": "vol-b", "Encrypted": False, "Size": 8, "VolumeType": "gp2",
         "State": "in-use", "Attachments": []},
    ]}

    with patch("services.aws_service._aws_client", return_value=ec2):
        result = AWSService().get_ec2_instance_volumes("i-12345678", region="eu-west-1")

    assert result["status"] == "healthy"
    assert [volume["volume_id"] for volume in result["volumes"]] == ["vol-a", "vol-b"]
    assert result["volumes"][0]["encrypted"] is True
    assert result["volumes"][0]["attachments"] == [
        {"device": "/dev/sda1", "state": "attached"}
    ]
    assert result["volumes"][1]["encrypted"] is False
    ec2.describe_volumes.assert_called_once_with(VolumeIds=["vol-a", "vol-b"])


def test_instance_without_ebs_volumes_returns_empty_list_without_volume_lookup():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{"BlockDeviceMappings": []}]}]}

    with patch("services.aws_service._aws_client", return_value=ec2):
        result = AWSService().get_ec2_instance_volumes("i-12345678")

    assert result == {
        "service": "ec2", "status": "healthy", "instance_id": "i-12345678", "volumes": []
    }
    ec2.describe_volumes.assert_not_called()


def test_instance_volume_provider_failure_is_returned_as_unhealthy():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{
        "BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-a"}}]
    }]}]}
    ec2.describe_volumes.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "private diagnostic"}}, "DescribeVolumes"
    )

    with patch("services.aws_service._aws_client", return_value=ec2):
        result = AWSService().get_ec2_instance_volumes("i-12345678")

    assert result["status"] == "unhealthy"
    assert "private diagnostic" in result["error"]
