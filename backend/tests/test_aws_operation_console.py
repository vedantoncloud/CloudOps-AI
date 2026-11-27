from conftest import console_response, read_console_source
from pathlib import Path


def test_operations_console_includes_aws_operation_failure_summary():
    html = read_console_source()
    assert "AWS operation failures" in html
    assert "/operations/aws-failures" in html
    assert 'id="awsFailureRows"' in html


def test_operations_console_includes_database_operation_outcomes():
    html = read_console_source()
    assert "Database operation outcomes" in html
    assert "/operations/database-failures" in html
    assert 'id="databaseFailureRows"' in html
