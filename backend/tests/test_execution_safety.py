from dataclasses import dataclass, field
from enum import Enum

import pytest

from autonomy.execution_safety import (
    ExecutionSafetyDecision,
    ExecutionSafetyGate,
)


class Status(str, Enum):
    PLANNED = "planned"
    APPROVED = "approved"


@dataclass
class Target:
    resource_id: str = "i-123"


@dataclass
class Action:
    action_id: str = "act-1"
    action_type: str = "scale"
    target: Target = field(default_factory=Target)
    rationale: str = "test action"
    status: Status = Status.APPROVED


@dataclass
class BlastRadius:
    impact_score: int = 10
    risk: str = "low"


@dataclass
class Decision:
    recommendation: str = "proceed"


def test_allow_dry_run_for_approved_action():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        decision=Decision("proceed"),
        approved=True,
        dry_run=True,
    )
    assert result.decision is ExecutionSafetyDecision.ALLOW
    assert result.execution_allowed is True
    assert result.eligible is True
    assert result.dry_run is True


def test_deny_upstream_block():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        decision=Decision("block"),
        dry_run=True,
    )
    assert result.decision is ExecutionSafetyDecision.DENY
    assert result.execution_allowed is False
    assert result.blocked is True


def test_review_upstream_review():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        decision=Decision("review"),
        dry_run=True,
    )
    assert result.decision is ExecutionSafetyDecision.REVIEW
    assert result.requires_human_approval is True


def test_deny_duplicate_idempotency():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        idempotency_key="action:act-1",
        idempotency_seen=True,
        dry_run=True,
    )
    assert result.decision is ExecutionSafetyDecision.DENY
    assert result.evidence["idempotency_seen"] is True


def test_review_high_blast_radius():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        blast_radius=BlastRadius(impact_score=80, risk="medium"),
        approved=True,
        dry_run=False,
    )
    assert result.decision is ExecutionSafetyDecision.REVIEW
    assert result.requires_human_approval is True
    assert result.evidence["impact_score"] == 80


def test_review_critical_blast_radius():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        blast_radius=BlastRadius(impact_score=20, risk="critical"),
        approved=True,
        dry_run=False,
    )
    assert result.decision is ExecutionSafetyDecision.REVIEW


def test_destructive_action_requires_approval():
    action = Action(action_type="terminate_instance", status=Status.PLANNED)
    result = ExecutionSafetyGate().evaluate(
        action,
        decision=Decision("proceed"),
        approved=False,
        dry_run=False,
    )
    assert result.destructive is True
    assert result.decision is ExecutionSafetyDecision.REVIEW
    assert result.execution_allowed is False


def test_approved_destructive_action_can_pass_in_dry_run():
    action = Action(action_type="terminate_instance")
    result = ExecutionSafetyGate().evaluate(
        action,
        decision=Decision("proceed"),
        approved=True,
        dry_run=True,
    )
    assert result.decision is ExecutionSafetyDecision.ALLOW
    assert result.destructive is True


def test_approved_destructive_action_can_execute_when_bounded():
    action = Action(action_type="terminate_instance")
    result = ExecutionSafetyGate().evaluate(
        action,
        decision=Decision("proceed"),
        blast_radius=BlastRadius(impact_score=20, risk="low"),
        approved=True,
        dry_run=False,
    )
    assert result.decision is ExecutionSafetyDecision.ALLOW
    assert result.execution_allowed is True


def test_non_destructive_unapproved_action_is_reviewed_when_not_dry_run():
    action = Action(status=Status.PLANNED)
    result = ExecutionSafetyGate().evaluate(
        action,
        decision=Decision("proceed"),
        approved=False,
        dry_run=False,
    )
    assert result.decision is ExecutionSafetyDecision.REVIEW
    assert result.requires_human_approval is True


def test_missing_action_identity_is_denied():
    action = Action(action_id="", action_type="review_cpu_utilization")
    result = ExecutionSafetyGate().evaluate(action, dry_run=True)
    assert result.decision is ExecutionSafetyDecision.DENY
    assert result.execution_allowed is False


def test_can_execute_matches_result():
    gate = ExecutionSafetyGate()
    allowed = gate.evaluate(Action(), approved=True, dry_run=False)
    review = gate.evaluate(
        Action(status=Status.PLANNED),
        approved=False,
        dry_run=False,
    )

    assert gate.can_execute(allowed) is True
    assert gate.can_execute(review) is False


def test_idempotency_key_is_preserved_in_evidence():
    result = ExecutionSafetyGate().evaluate(
        Action(),
        idempotency_key="action:act-1",
        dry_run=True,
    )
    assert result.evidence["idempotency_key_present"] is True


def test_custom_blast_radius_limit():
    gate = ExecutionSafetyGate(max_impact_score=20)
    result = gate.evaluate(
        Action(),
        blast_radius=BlastRadius(impact_score=21, risk="low"),
        approved=True,
        dry_run=False,
    )
    assert result.decision is ExecutionSafetyDecision.REVIEW


def test_invalid_blast_radius_limit_is_rejected():
    with pytest.raises(ValueError):
        ExecutionSafetyGate(max_impact_score=-1)
