from autonomy.cost_optimizer import CostOptimizer, CostSignal


def test_low_cpu_ec2_is_underutilized():
    result = CostOptimizer().analyze_ec2(
        "i-123",
        average_cpu=4.5,
    )

    assert result.signal == CostSignal.UNDERUTILIZED
    assert result.estimated_monthly_savings is None
    assert result.confidence == "medium"


def test_ec2_cost_estimate_is_explicitly_estimated():
    result = CostOptimizer().analyze_ec2(
        "i-123",
        average_cpu=5,
        monthly_cost=100,
    )

    assert result.signal == CostSignal.UNDERUTILIZED
    assert result.estimated_monthly_savings == 30.0
    assert result.confidence == "estimated"
    assert result.details["savings_is_estimate"] is True


def test_normal_cpu_has_no_immediate_cost_opportunity():
    result = CostOptimizer().analyze_ec2(
        "i-123",
        average_cpu=35,
    )

    assert result.signal == CostSignal.NO_BILLING_DATA
    assert result.estimated_monthly_savings is None


def test_missing_cpu_data_does_not_invent_savings():
    result = CostOptimizer().analyze_ec2(
        "i-123",
        average_cpu=None,
    )

    assert result.signal == CostSignal.NO_BILLING_DATA
    assert result.estimated_monthly_savings is None
    assert result.confidence == "low"


def test_ec2_cpu_must_be_valid():
    try:
        CostOptimizer().analyze_ec2("i-123", average_cpu=101)
    except ValueError as exc:
        assert str(exc) == "average_cpu must be between 0 and 100"
    else:
        raise AssertionError("Expected ValueError")


def test_negative_ec2_cost_is_rejected():
    try:
        CostOptimizer().analyze_ec2(
            "i-123",
            average_cpu=5,
            monthly_cost=-1,
        )
    except ValueError as exc:
        assert str(exc) == "monthly_cost cannot be negative"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_s3_bucket_is_unused():
    result = CostOptimizer().analyze_s3(
        "my-bucket",
        object_count=0,
        total_size_bytes=0,
    )

    assert result.signal == CostSignal.UNUSED
    assert result.estimated_monthly_savings is None


def test_s3_storage_can_generate_optimization_opportunity():
    result = CostOptimizer().analyze_s3(
        "my-bucket",
        object_count=1000,
        total_size_bytes=1024 * 1024 * 100,
    )

    assert result.signal == CostSignal.STORAGE_OPTIMIZATION
    assert result.estimated_monthly_savings is None
    assert result.details["savings_is_estimate"] is False


def test_missing_s3_data_does_not_invent_savings():
    result = CostOptimizer().analyze_s3(
        "my-bucket",
        object_count=None,
        total_size_bytes=None,
    )

    assert result.signal == CostSignal.NO_BILLING_DATA
    assert result.estimated_monthly_savings is None


def test_negative_s3_values_are_rejected():
    try:
        CostOptimizer().analyze_s3(
            "my-bucket",
            object_count=-1,
            total_size_bytes=100,
        )
    except ValueError as exc:
        assert str(exc) == "object_count cannot be negative"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_bucket_name_is_rejected():
    try:
        CostOptimizer().analyze_s3(
            "",
            object_count=0,
            total_size_bytes=0,
        )
    except ValueError as exc:
        assert str(exc) == "bucket_name cannot be empty"
    else:
        raise AssertionError("Expected ValueError")
