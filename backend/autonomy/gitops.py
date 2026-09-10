from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any


class GitOpsChangeStatus(str, Enum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    APPLIED = "applied"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class GitOpsChange:
    resource_type: str
    resource_id: str
    field: str
    desired_value: Any
    current_value: Any | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.resource_type.strip():
            raise ValueError("resource_type cannot be empty")
        if not self.resource_id.strip():
            raise ValueError("resource_id cannot be empty")
        if not self.field.strip():
            raise ValueError("field cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "field": self.field,
            "desired_value": self.desired_value,
            "current_value": self.current_value,
            "reason": self.reason,
        }


@dataclass
class GitOpsChangeSet:
    change_id: str
    source_action_id: str
    changes: list[GitOpsChange]
    status: GitOpsChangeStatus = GitOpsChangeStatus.PROPOSED
    requires_approval: bool = True
    approved_by: str | None = None
    commit_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.change_id.strip():
            raise ValueError("change_id cannot be empty")
        if not self.source_action_id.strip():
            raise ValueError("source_action_id cannot be empty")

        if not self.changes:
            raise ValueError("changes cannot be empty")

        if self.requires_approval and self.status == GitOpsChangeStatus.PROPOSED:
            self.status = GitOpsChangeStatus.PENDING_APPROVAL

    @property
    def change_count(self) -> int:
        return len(self.changes)

    def approve(self, approved_by: str) -> None:
        if self.status != GitOpsChangeStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only pending GitOps changes can be approved"
            )

        if not approved_by.strip():
            raise ValueError("approved_by cannot be empty")

        self.approved_by = approved_by
        self.status = GitOpsChangeStatus.APPROVED

    def reject(self, rejected_by: str, reason: str) -> None:
        if self.status != GitOpsChangeStatus.PENDING_APPROVAL:
            raise ValueError(
                "Only pending GitOps changes can be rejected"
            )

        if not rejected_by.strip():
            raise ValueError("rejected_by cannot be empty")

        if not reason.strip():
            raise ValueError("rejection reason cannot be empty")

        self.status = GitOpsChangeStatus.REJECTED
        self.metadata["rejected_by"] = rejected_by
        self.metadata["rejection_reason"] = reason

    def to_manifest(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "source_action_id": self.source_action_id,
            "status": self.status.value,
            "requires_approval": self.requires_approval,
            "approved_by": self.approved_by,
            "commit_message": self.commit_message,
            "changes": [change.to_dict() for change in self.changes],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GitOpsApplyResult:
    change_id: str
    success: bool
    dry_run: bool
    status: GitOpsChangeStatus
    applied_changes: int
    message: str


class GitOpsEngine:
    """Create and safely apply declarative infrastructure changes."""

    def create_change_set(
        self,
        *,
        source_action_id: str,
        changes: list[GitOpsChange],
        requires_approval: bool = True,
        commit_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GitOpsChangeSet:
        if not source_action_id.strip():
            raise ValueError("source_action_id cannot be empty")

        if not changes:
            raise ValueError("changes cannot be empty")

        canonical = json.dumps(
            [change.to_dict() for change in changes],
            sort_keys=True,
            default=str,
        )

        digest = hashlib.sha256(
            f"{source_action_id}:{canonical}".encode("utf-8")
        ).hexdigest()[:16]

        change_id = f"change-{digest}"

        return GitOpsChangeSet(
            change_id=change_id,
            source_action_id=source_action_id,
            changes=list(changes),
            requires_approval=requires_approval,
            commit_message=commit_message
            or f"cloudops-ai: apply {len(changes)} infrastructure change(s)",
            metadata=dict(metadata or {}),
        )

    def validate(self, change_set: GitOpsChangeSet) -> list[str]:
        errors: list[str] = []

        if not change_set.changes:
            errors.append("change set contains no changes")

        seen: set[tuple[str, str, str]] = set()

        for change in change_set.changes:
            key = (
                change.resource_type,
                change.resource_id,
                change.field,
            )

            if key in seen:
                errors.append(
                    "duplicate change target: "
                    f"{change.resource_type}/{change.resource_id}/{change.field}"
                )

            seen.add(key)

        return errors

    def approve(
        self,
        change_set: GitOpsChangeSet,
        approved_by: str,
    ) -> GitOpsChangeSet:
        change_set.approve(approved_by)
        return change_set

    def reject(
        self,
        change_set: GitOpsChangeSet,
        rejected_by: str,
        reason: str,
    ) -> GitOpsChangeSet:
        change_set.reject(rejected_by, reason)
        return change_set

    def apply(
        self,
        change_set: GitOpsChangeSet,
        *,
        dry_run: bool = True,
    ) -> GitOpsApplyResult:
        errors = self.validate(change_set)

        if errors:
            change_set.status = GitOpsChangeStatus.FAILED
            return GitOpsApplyResult(
                change_id=change_set.change_id,
                success=False,
                dry_run=dry_run,
                status=GitOpsChangeStatus.FAILED,
                applied_changes=0,
                message="; ".join(errors),
            )

        if change_set.requires_approval and (
            change_set.status != GitOpsChangeStatus.APPROVED
        ):
            return GitOpsApplyResult(
                change_id=change_set.change_id,
                success=False,
                dry_run=dry_run,
                status=change_set.status,
                applied_changes=0,
                message="GitOps change requires human approval before apply",
            )

        if change_set.status == GitOpsChangeStatus.REJECTED:
            return GitOpsApplyResult(
                change_id=change_set.change_id,
                success=False,
                dry_run=dry_run,
                status=GitOpsChangeStatus.REJECTED,
                applied_changes=0,
                message="Rejected GitOps change cannot be applied",
            )

        if not dry_run:
            return GitOpsApplyResult(
                change_id=change_set.change_id,
                success=False,
                dry_run=False,
                status=GitOpsChangeStatus.FAILED,
                applied_changes=0,
                message=(
                    "Real infrastructure mutation is disabled; "
                    "only dry-run GitOps apply is supported"
                ),
            )

        change_set.status = GitOpsChangeStatus.APPLIED

        return GitOpsApplyResult(
            change_id=change_set.change_id,
            success=True,
            dry_run=True,
            status=GitOpsChangeStatus.APPLIED,
            applied_changes=len(change_set.changes),
            message="GitOps changes validated and applied in dry-run mode",
        )

    def verify(
        self,
        change_set: GitOpsChangeSet,
        *,
        observed_values: dict[str, Any] | None = None,
    ) -> bool:
        if change_set.status != GitOpsChangeStatus.APPLIED:
            raise ValueError(
                "Only applied GitOps changes can be verified"
            )

        if observed_values is None:
            change_set.status = GitOpsChangeStatus.VERIFIED
            return True

        for change in change_set.changes:
            key = (
                f"{change.resource_type}/"
                f"{change.resource_id}/"
                f"{change.field}"
            )

            if key not in observed_values:
                change_set.status = GitOpsChangeStatus.FAILED
                return False

            if observed_values[key] != change.desired_value:
                change_set.status = GitOpsChangeStatus.FAILED
                return False

        change_set.status = GitOpsChangeStatus.VERIFIED
        return True
