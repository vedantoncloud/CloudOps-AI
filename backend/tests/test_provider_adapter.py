from unittest.mock import Mock

from autonomy.aws_provider import AWSProvider
from autonomy.provider import CloudProvider


class TestCloudProvider:
    def test_provider_is_abstract(self):
        assert CloudProvider.__abstractmethods__ == {
            "provider_name",
            "get_ec2_instances",
            "get_ec2_summary",
            "get_s3_buckets",
        }


class TestAWSProvider:
    def test_provider_name(self):
        service = Mock()
        provider = AWSProvider(service)

        assert provider.provider_name == "aws"

    def test_uses_injected_service(self):
        service = Mock()
        provider = AWSProvider(service)

        assert provider.service is service

    def test_ec2_instances_delegates(self):
        service = Mock()
        service.get_ec2_instances.return_value = {
            "status": "healthy",
            "instances": [{"instance_id": "i-123"}],
        }

        provider = AWSProvider(service)

        result = provider.get_ec2_instances("running", "Environment=prod")

        service.get_ec2_instances.assert_called_once_with(
            "running",
            "Environment=prod",
        )
        assert result == {
            "status": "healthy",
            "instances": [{"instance_id": "i-123"}],
        }

    def test_ec2_instances_supports_defaults(self):
        service = Mock()
        service.get_ec2_instances.return_value = {"instances": []}

        provider = AWSProvider(service)

        result = provider.get_ec2_instances()

        service.get_ec2_instances.assert_called_once_with(None, None)
        assert result == {"instances": []}

    def test_ec2_summary_delegates(self):
        service = Mock()
        service.get_ec2_summary.return_value = {
            "status": "healthy",
            "running": 3,
        }

        provider = AWSProvider(service)

        result = provider.get_ec2_summary()

        service.get_ec2_summary.assert_called_once_with()
        assert result == {
            "status": "healthy",
            "running": 3,
        }

    def test_s3_buckets_delegates(self):
        service = Mock()
        service.get_s3_buckets.return_value = {
            "status": "healthy",
            "buckets": ["bucket-a"],
        }

        provider = AWSProvider(service)

        result = provider.get_s3_buckets()

        service.get_s3_buckets.assert_called_once_with()
        assert result == {
            "status": "healthy",
            "buckets": ["bucket-a"],
        }

    def test_adapter_does_not_expose_mutation_api(self):
        service = Mock()
        provider = AWSProvider(service)

        public_methods = {
            name
            for name in dir(provider)
            if not name.startswith("_")
        }

        assert "terminate_instance" not in public_methods
        assert "delete_bucket" not in public_methods
        assert "stop_instance" not in public_methods
        assert "start_instance" not in public_methods
        assert "modify_instance" not in public_methods
