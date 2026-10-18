from pathlib import Path


def test_operations_console_includes_aws_operation_failure_summary():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert "AWS operation failures" in html
    assert "/operations/aws-failures" in html
    assert 'id="awsFailureRows"' in html


def test_operations_console_includes_database_operation_outcomes():
    html = (Path(__file__).parents[1] / "static" / "console.html").read_text(encoding="utf-8")
    assert "Database operation outcomes" in html
    assert "/operations/database-failures" in html
    assert 'id="databaseFailureRows"' in html
