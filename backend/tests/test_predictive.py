from autonomy.action_models import RiskLevel
from autonomy.predictive import (
    PredictionSignal,
    PredictiveOperationsEngine,
)


def test_insufficient_data_does_not_predict():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [20, 30],
    )

    assert result.signal == PredictionSignal.INSUFFICIENT_DATA
    assert result.predicted_value is None
    assert result.confidence is None
    assert result.predicted_risk is None


def test_increasing_trend_is_detected():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [30, 40, 50, 60],
    )

    assert result.signal == PredictionSignal.INCREASING
    assert result.predicted_value == 70
    assert result.predicted_risk == RiskLevel.MEDIUM


def test_decreasing_trend_is_detected():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [80, 70, 60, 50],
    )

    assert result.signal == PredictionSignal.DECREASING
    assert result.predicted_value == 40
    assert result.predicted_risk == RiskLevel.LOW


def test_stable_trend_is_detected():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [50, 50, 50, 50],
    )

    assert result.signal == PredictionSignal.STABLE
    assert result.predicted_value == 50
    assert result.predicted_risk == RiskLevel.LOW


def test_warning_threshold_predicts_high_risk():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [60, 70, 80],
        warning_threshold=85,
        critical_threshold=95,
    )

    assert result.predicted_value == 90
    assert result.predicted_risk == RiskLevel.HIGH


def test_critical_threshold_predicts_critical_risk():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [70, 80, 90],
        warning_threshold=85,
        critical_threshold=95,
    )

    assert result.predicted_value == 100
    assert result.predicted_risk == RiskLevel.CRITICAL


def test_confidence_increases_with_more_history():
    engine = PredictiveOperationsEngine()

    short = engine.predict(
        "i-123",
        "cpu",
        [10, 20, 30],
    )

    long = engine.predict(
        "i-123",
        "cpu",
        list(range(10, 31)),
    )

    assert long.confidence >= short.confidence


def test_prediction_never_goes_below_zero():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [20, 10, 0],
    )

    assert result.predicted_value == 0


def test_negative_observation_is_rejected():
    try:
        PredictiveOperationsEngine().predict(
            "i-123",
            "cpu",
            [10, -1, 20],
        )
    except ValueError as exc:
        assert str(exc) == "observations cannot contain negative values"
    else:
        raise AssertionError("Expected ValueError")


def test_invalid_threshold_order_is_rejected():
    try:
        PredictiveOperationsEngine().predict(
            "i-123",
            "cpu",
            [10, 20, 30],
            warning_threshold=90,
            critical_threshold=80,
        )
    except ValueError as exc:
        assert "warning_threshold cannot exceed critical_threshold" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_empty_resource_id_is_rejected():
    try:
        PredictiveOperationsEngine().predict(
            "",
            "cpu",
            [10, 20, 30],
        )
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_metric_is_rejected():
    try:
        PredictiveOperationsEngine().predict(
            "i-123",
            "",
            [10, 20, 30],
        )
    except ValueError as exc:
        assert str(exc) == "metric cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_prediction_contains_operational_details():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "cpu",
        [20, 30, 40],
    )

    assert result.details["observation_count"] == 3
    assert result.details["current_value"] == 40
    assert result.details["model"] == "recent-three-point-trend"


def test_result_preserves_resource_and_metric():
    result = PredictiveOperationsEngine().predict(
        "i-123",
        "network",
        [10, 20, 30],
    )

    assert result.resource_id == "i-123"
    assert result.metric == "network"
