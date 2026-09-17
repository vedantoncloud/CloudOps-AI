from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionSafetyDecision(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


@dataclass(frozen=True)
class ExecutionSafetyResult:
    decision: ExecutionSafetyDecision
    execution_allowed: bool
    requires_human_approval: bool
    dry_run: bool
    destructive: bool
    reasons: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.decision == ExecutionSafetyDecision.DENY

    @property
    def eligible(self) -> bool:
        return self.execution_allowed and not self.requires_human_approval


class ExecutionSafetyGate:
    """Final bounded-autonomy gate immediately before the executor.

    This layer never performs infrastructure mutations. It only decides whether
    an already-planned action is eligible to reach the existing executor.
    """

    DEFAULT_MAX_IMPACT_SCORE = 60

    # Explicitly conservative: these action families need an additional safety
    # check even when the upstream decision says PROCEED.
    DESTRUCTIVE_KEYWORDS = (
        "delete",
        "terminate",
        "destroy",
        "remove",
        "revoke",
        "detach",
        "purge",
        "drop",
        "decommission",
    )

    def __init__(self, *, max_impact_score: int = DEFAULT_MAX_IMPACT_SCORE) -> None:
        if max_impact_score < 0:
            raise ValueError("max_impact_score must be non-negative")
        self.max_impact_score = max_impact_score

    def evaluate(
        self,
        action: Any,
        *,
        decision: Any = None,
        blast_radius: Any = None,
        idempotency_key: str | None = None,
        idempotency_seen: bool = False,
        approved: bool | None = None,
        dry_run: bool = True,
    ) -> ExecutionSafetyResult:
        action_id = self._text(getattr(action, "action_id", None))
        action_type = self._text(getattr(action, "action_type", None))
        resource_id = self._text(
            getattr(getattr(action, "target", None), "resource_id", None)
        )

        reasons: list[str] = []
        evidence: dict[str, Any] = {
            "action_id": action_id,
            "action_type": action_type,
            "resource_id": resource_id,
            "dry_run": dry_run,
            "idempotency_key_present": bool(idempotency_key),
            "idempotency_seen": idempotency_seen,
            "max_impact_score": self.max_impact_score,
        }

        if not action_id or not action_type or not resource_id:
            return self._deny(
                "Action identity is incomplete.",
                evidence=evidence,
                destructive=self._is_destructive(action_type),
                dry_run=dry_run,
            )

        destructive = self._is_destructive(action_type)
        evidence["destructive"] = destructive

        upstream = self._decision_value(decision)
        evidence["upstream_decision"] = upstream

        if upstream in {"deny", "block", "blocked"}:
            return self._deny(
                "Upstream decision blocks execution.",
                evidence=evidence,
                destructive=destructive,
                dry_run=dry_run,
            )

        if idempotency_seen:
            return self._deny(
                "Idempotency check indicates this action was already processed.",
                evidence=evidence,
                destructive=destructive,
                dry_run=dry_run,
            )

        impact_score = self._impact_score(blast_radius)
        risk = self._risk_value(blast_radius)
        if impact_score is not None:
            evidence["impact_score"] = impact_score
        if risk is not None:
            evidence["blast_radius_risk"] = risk

        if impact_score is not None and impact_score > self.max_impact_score:
            return self._review(
                "Blast-radius impact exceeds the automatic execution limit.",
                evidence=evidence,
                destructive=destructive,
                dry_run=dry_run,
            )

        if risk in {"high", "critical"}:
            return self._review(
                "Blast-radius risk requires human review before execution.",
                evidence=evidence,
                destructive=destructive,
                dry_run=dry_run,
            )

        if upstream in {"review", "requires_review", "human_review"}:
            return self._review(
                "Upstream decision requires human review.",
                evidence=evidence,
                destructive=destructive,
                dry_run=dry_run,
            )

        if approved is None:
            approved = self._action_is_approved(action)

        evidence["approved"] = approved

        if destructive:
            if not approved:
                return self._review(
                    "Destructive actions require explicit human approval.",
                    evidence=evidence,
                    destructive=True,
                    dry_run=dry_run,
                )
            reasons.append("Destructive action has explicit approval.")

        # Dry-run is always eligible because it does not mutate infrastructure.
        if dry_run:
            reasons.append("Dry-run mode prevents infrastructure mutation.")
            return ExecutionSafetyResult(
                decision=ExecutionSafetyDecision.ALLOW,
                execution_allowed=True,
                requires_human_approval=False,
                dry_run=True,
                destructive=destructive,
                reasons=tuple(reasons),
                evidence=evidence,
            )

        if not approved:
            return self._review(
                "Execution requires an approved action.",
                evidence=evidence,
                destructive=destructive,
                dry_run=False,
            )

        reasons.append("Action passed the bounded execution safety checks.")
        return ExecutionSafetyResult(
            decision=ExecutionSafetyDecision.ALLOW,
            execution_allowed=True,
            requires_human_approval=False,
            dry_run=False,
            destructive=destructive,
            reasons=tuple(reasons),
            evidence=evidence,
        )

    def can_execute(self, result: ExecutionSafetyResult) -> bool:
        return result.execution_allowed and not result.requires_human_approval

    @classmethod
    def _is_destructive(cls, action_type: str) -> bool:
        normalized = action_type.lower().replace("-", "_").replace(" ", "_")
        return any(keyword in normalized for keyword in cls.DESTRUCTIVE_KEYWORDS)

    @staticmethod
    def _text(value: Any) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _decision_value(decision: Any) -> str:
        if decision is None:
            return ""
        value = getattr(decision, "recommendation", decision)
        value = getattr(value, "value", value)
        return str(value).strip().lower()

    @staticmethod
    def _action_is_approved(action: Any) -> bool:
        value = getattr(action, "status", None)
        value = getattr(value, "value", value)
        return str(value).strip().lower() == "approved"

    @staticmethod
    def _impact_score(blast_radius: Any) -> int | None:
        if blast_radius is None:
            return None
        value = getattr(blast_radius, "impact_score", None)
        if value is None and isinstance(blast_radius, dict):
            value = blast_radius.get("impact_score")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _risk_value(blast_radius: Any) -> str | None:
        if blast_radius is None:
            return None
        value = getattr(blast_radius, "risk", None)
        if value is None and isinstance(blast_radius, dict):
            value = blast_radius.get("risk")
        value = getattr(value, "value", value)
        return str(value).strip().lower() if value is not None else None

    @staticmethod
    def _deny(
        reason: str,
        *,
        evidence: dict[str, Any],
        destructive: bool,
        dry_run: bool,
    ) -> ExecutionSafetyResult:
        return ExecutionSafetyResult(
            decision=ExecutionSafetyDecision.DENY,
            execution_allowed=False,
            requires_human_approval=False,
            dry_run=dry_run,
            destructive=destructive,
            reasons=(reason,),
            evidence=evidence,
        )

    @staticmethod
    def _review(
        reason: str,
        *,
        evidence: dict[str, Any],
        destructive: bool,
        dry_run: bool,
    ) -> ExecutionSafetyResult:
        return ExecutionSafetyResult(
            decision=ExecutionSafetyDecision.REVIEW,
            execution_allowed=False,
            requires_human_approval=True,
            dry_run=dry_run,
            destructive=destructive,
            reasons=(reason,),
            evidence=evidence,
        )
