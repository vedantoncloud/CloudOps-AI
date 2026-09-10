from dataclasses import dataclass, field
from enum import Enum
from statistics import mean
from typing import Any

from autonomy.action_models import RiskLevel


class PredictionSignal(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class PredictionResult:
    resource_id: str
    metric: str
    signal: PredictionSignal
    predicted_risk: RiskLevel | None
    predicted_value: float | None
    confidence: float | None
    recommendation: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class PredictiveOperationsEngine:
    """Detect metric trends and identify potential future operational risk."""

    def predict(
        self,
        resource_id: str,
        metric: str,
        observations: list[float],
        *,
        warning_threshold: float | None = None,
        critical_threshold: float | None = None,
    ) -> PredictionResult:
        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        if not metric or not metric.strip():
            raise ValueError("metric cannot be empty")

        if any(value < 0 for value in observations):
            raise ValueError("observations cannot contain negative values")

        if warning_threshold is not None and warning_threshold < 0:
            raise ValueError("warning_threshold cannot be negative")

        if critical_threshold is not None and critical_threshold < 0:
            raise ValueError("critical_threshold cannot be negative")

        if (
            warning_threshold is not None
            and critical_threshold is not None
            and warning_threshold > critical_threshold
        ):
            raise ValueError(
                "warning_threshold cannot exceed critical_threshold"
            )

        if len(observations) < 3:
            return PredictionResult(
                resource_id=resource_id,
                metric=metric,
                signal=PredictionSignal.INSUFFICIENT_DATA,
                predicted_risk=None,
                predicted_value=None,
                confidence=None,
                recommendation="Collect at least 3 observations before prediction.",
                reason="Insufficient historical observations.",
                details={
                    "observation_count": len(observations),
                    "prediction_available": False,
                },
            )

        recent = observations[-3:]
        differences = [
            recent[index + 1] - recent[index]
            for index in range(len(recent) - 1)
        ]

        average_change = mean(differences)
        current_value = observations[-1]
        predicted_value = round(max(0, current_value + average_change), 4)

        if all(change > 0 for change in differences):
            signal = PredictionSignal.INCREASING
        elif all(change < 0 for change in differences):
            signal = PredictionSignal.DECREASING
        else:
            signal = PredictionSignal.STABLE

        predicted_risk = None

        if critical_threshold is not None and predicted_value >= critical_threshold:
            predicted_risk = RiskLevel.CRITICAL
        elif warning_threshold is not None and predicted_value >= warning_threshold:
            predicted_risk = RiskLevel.HIGH
        elif signal == PredictionSignal.INCREASING:
            predicted_risk = RiskLevel.MEDIUM
        else:
            predicted_risk = RiskLevel.LOW

        confidence = round(
            min(0.95, 0.5 + min(0.45, len(observations) * 0.03)),
            2,
        )

        if signal == PredictionSignal.INCREASING:
            recommendation = "Investigate the increasing trend and consider preventive action."
            reason = (
                f"{metric} is increasing; predicted next value is "
                f"{predicted_value:.4f}."
            )
        elif signal == PredictionSignal.DECREASING:
            recommendation = "Continue monitoring the decreasing trend."
            reason = (
                f"{metric} is decreasing; predicted next value is "
                f"{predicted_value:.4f}."
            )
        else:
            recommendation = "Continue monitoring; no clear trend detected."
            reason = (
                f"{metric} has no consistent directional trend; "
                f"predicted next value is {predicted_value:.4f}."
            )

        return PredictionResult(
            resource_id=resource_id,
            metric=metric,
            signal=signal,
            predicted_risk=predicted_risk,
            predicted_value=predicted_value,
            confidence=confidence,
            recommendation=recommendation,
            reason=reason,
            details={
                "observation_count": len(observations),
                "current_value": current_value,
                "average_change": round(average_change, 4),
                "model": "recent-three-point-trend",
            },
        )
