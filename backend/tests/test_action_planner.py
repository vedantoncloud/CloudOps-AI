from autonomy.action_models import ActionStatus, RiskLevel
from autonomy.action_planner import ActionPlanner


def test_plan_ec2_action():
    planner = ActionPlanner()

    plan = planner.plan_ec2_action(
        instance_id="i-123456789",
        action_type="stop_instance",
        reason="Instance has remained idle.",
        risk=RiskLevel.MEDIUM,
    )

    assert plan.action_type == "stop_instance"
    assert plan.target.resource_type == "ec2_instance"
    assert plan.target.resource_id == "i-123456789"
    assert plan.reason == "Instance has remained idle."
    assert plan.risk == RiskLevel.MEDIUM
    assert plan.requires_approval is True
    assert plan.rollback_available is False
    assert plan.status == ActionStatus.PLANNED


def test_plan_ec2_action_with_metadata_and_rollback():
    planner = ActionPlanner()

    plan = planner.plan_ec2_action(
        instance_id="i-987654321",
        action_type="restart_instance",
        reason="Instance requires recovery.",
        risk=RiskLevel.HIGH,
        metadata={"region": "ap-south-1"},
        rollback_available=True,
    )

    assert plan.target.metadata["region"] == "ap-south-1"
    assert plan.rollback_available is True
    assert plan.requires_approval is True


def test_plan_s3_action():
    planner = ActionPlanner()

    plan = planner.plan_s3_action(
        bucket_name="example-bucket",
        action_type="review_bucket_access",
        reason="Bucket security configuration requires review.",
        risk=RiskLevel.MEDIUM,
    )

    assert plan.action_type == "review_bucket_access"
    assert plan.target.resource_type == "s3_bucket"
    assert plan.target.resource_id == "example-bucket"
    assert plan.reason == "Bucket security configuration requires review."
    assert plan.risk == RiskLevel.MEDIUM
    assert plan.requires_approval is True
    assert plan.status == ActionStatus.PLANNED


def test_plan_s3_action_with_metadata():
    planner = ActionPlanner()

    plan = planner.plan_s3_action(
        bucket_name="data-bucket",
        action_type="review_storage",
        reason="Storage optimization opportunity detected.",
        risk=RiskLevel.LOW,
        metadata={"prefix": "logs/"},
    )

    assert plan.target.metadata["prefix"] == "logs/"
    assert plan.risk == RiskLevel.LOW
    assert plan.requires_approval is True


def test_planner_does_not_execute_actions():
    planner = ActionPlanner()

    plan = planner.plan_ec2_action(
        instance_id="i-123456789",
        action_type="stop_instance",
        reason="Idle instance detected.",
        risk=RiskLevel.MEDIUM,
    )

    assert plan.status == ActionStatus.PLANNED


def test_high_cpu_insight_creates_ec2_action_plan():
    planner = ActionPlanner()

    insight = {
        "type": "high_cpu_utilization",
        "severity": "high",
        "message": "EC2 instance CPU utilization is 80% or higher.",
        "recommendation": "Investigate CPU-intensive workloads and consider scaling or workload optimization.",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "investigate_cpu_capacity"
    assert plan.target.resource_type == "ec2_instance"
    assert plan.target.resource_id == "i-123456789"
    assert plan.risk == RiskLevel.HIGH
    assert plan.requires_approval is True
    assert plan.status == ActionStatus.PLANNED
    assert plan.target.metadata["insight_type"] == "high_cpu_utilization"


def test_medium_cpu_insight_creates_medium_risk_plan():
    planner = ActionPlanner()

    insight = {
        "type": "elevated_cpu_utilization",
        "severity": "medium",
        "message": "EC2 instance CPU utilization is elevated.",
        "recommendation": "Review recent workload changes and monitor CPU usage for sustained growth.",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "review_cpu_utilization"
    assert plan.risk == RiskLevel.MEDIUM
    assert plan.requires_approval is True


def test_instance_status_issue_creates_high_risk_plan():
    planner = ActionPlanner()

    insight = {
        "type": "instance_status_issue",
        "severity": "high",
        "message": "EC2 instance status check is impaired.",
        "recommendation": "Investigate the instance status check failure and review AWS system or instance events.",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "investigate_instance_status"
    assert plan.risk == RiskLevel.HIGH


def test_missing_cpu_data_creates_low_risk_plan():
    planner = ActionPlanner()

    insight = {
        "type": "cpu_data_missing",
        "severity": "low",
        "message": "No recent CPU utilization datapoint is available.",
        "recommendation": "Verify CloudWatch monitoring and confirm that the instance is reporting metrics.",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "verify_cloudwatch_cpu_monitoring"
    assert plan.risk == RiskLevel.LOW


def test_unsupported_ec2_insight_does_not_create_action():
    planner = ActionPlanner()

    insight = {
        "type": "unknown_future_insight",
        "severity": "medium",
        "message": "Some future insight.",
        "recommendation": "Some future recommendation.",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is None


def test_invalid_ec2_insight_does_not_create_action():
    planner = ActionPlanner()

    insight = {
        "type": "high_cpu_utilization",
        "severity": "high",
    }

    plan = planner.plan_from_ec2_insight(
        instance_id="i-123456789",
        insight=insight,
    )

    assert plan is None


def test_multiple_ec2_insights_create_multiple_plans():
    planner = ActionPlanner()

    insights = [
        {
            "type": "high_cpu_utilization",
            "severity": "high",
            "message": "High CPU detected.",
            "recommendation": "Investigate CPU usage.",
        },
        {
            "type": "network_data_missing",
            "severity": "low",
            "message": "Network data is unavailable.",
            "recommendation": "Verify network monitoring.",
        },
    ]

    plans = planner.plan_from_ec2_insights(
        instance_id="i-123456789",
        insights=insights,
    )

    assert len(plans) == 2
    assert plans[0].action_type == "investigate_cpu_capacity"
    assert plans[0].risk == RiskLevel.HIGH
    assert plans[1].action_type == "verify_cloudwatch_network_monitoring"
    assert plans[1].risk == RiskLevel.LOW


def test_empty_bucket_insight_creates_low_risk_s3_plan():
    planner = ActionPlanner()

    insight = {
        "type": "empty_bucket",
        "severity": "low",
        "message": "Bucket contains no objects.",
        "recommendation": "Verify whether this bucket is still required.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="example-bucket",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "review_bucket_usage"
    assert plan.target.resource_type == "s3_bucket"
    assert plan.target.resource_id == "example-bucket"
    assert plan.risk == RiskLevel.LOW
    assert plan.requires_approval is True
    assert plan.target.metadata["insight_type"] == "empty_bucket"


def test_large_object_insight_creates_medium_risk_s3_plan():
    planner = ActionPlanner()

    insight = {
        "type": "large_object",
        "severity": "medium",
        "message": "Bucket contains an object larger than 1 GB.",
        "recommendation": "Review the object and consider compression or lifecycle policies.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="data-bucket",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "review_large_object"
    assert plan.risk == RiskLevel.MEDIUM
    assert plan.requires_approval is True


def test_high_object_count_insight_creates_medium_risk_s3_plan():
    planner = ActionPlanner()

    insight = {
        "type": "high_object_count",
        "severity": "medium",
        "message": "Bucket contains a very large number of objects.",
        "recommendation": "Review object lifecycle and prefix organization to reduce management overhead.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="logs-bucket",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "review_object_lifecycle"
    assert plan.risk == RiskLevel.MEDIUM


def test_many_small_objects_insight_creates_low_risk_s3_plan():
    planner = ActionPlanner()

    insight = {
        "type": "many_small_objects",
        "severity": "low",
        "message": "Bucket contains many relatively small objects.",
        "recommendation": "Consider combining small files where practical and review storage access patterns.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="data-bucket",
        insight=insight,
    )

    assert plan is not None
    assert plan.action_type == "review_small_object_optimization"
    assert plan.risk == RiskLevel.LOW


def test_s3_insight_preserves_prefix():
    planner = ActionPlanner()

    insight = {
        "type": "large_object",
        "severity": "medium",
        "message": "Bucket contains an object larger than 1 GB.",
        "recommendation": "Review the object and consider compression or lifecycle policies.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="data-bucket",
        insight=insight,
        prefix="logs/2026/",
    )

    assert plan is not None
    assert plan.target.metadata["prefix"] == "logs/2026/"


def test_unsupported_s3_insight_does_not_create_action():
    planner = ActionPlanner()

    insight = {
        "type": "unknown_future_insight",
        "severity": "medium",
        "message": "Future insight.",
        "recommendation": "Future recommendation.",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="example-bucket",
        insight=insight,
    )

    assert plan is None


def test_invalid_s3_insight_does_not_create_action():
    planner = ActionPlanner()

    insight = {
        "type": "large_object",
        "severity": "medium",
    }

    plan = planner.plan_from_s3_insight(
        bucket_name="example-bucket",
        insight=insight,
    )

    assert plan is None


def test_multiple_s3_insights_create_multiple_plans():
    planner = ActionPlanner()

    insights = [
        {
            "type": "empty_bucket",
            "severity": "low",
            "message": "Bucket contains no objects.",
            "recommendation": "Verify whether this bucket is still required.",
        },
        {
            "type": "large_object",
            "severity": "medium",
            "message": "Bucket contains an object larger than 1 GB.",
            "recommendation": "Review the object and consider compression or lifecycle policies.",
        },
    ]

    plans = planner.plan_from_s3_insights(
        bucket_name="example-bucket",
        insights=insights,
    )

    assert len(plans) == 2
    assert plans[0].action_type == "review_bucket_usage"
    assert plans[0].risk == RiskLevel.LOW
    assert plans[1].action_type == "review_large_object"
    assert plans[1].risk == RiskLevel.MEDIUM
