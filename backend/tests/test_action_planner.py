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

    # Planner only creates a plan; execution must happen elsewhere.
    assert plan.status == ActionStatus.PLANNED