from autonomy.gitops import (
    GitOpsChange,
    GitOpsChangeSet,
    GitOpsChangeStatus,
    GitOpsEngine,
)


def make_change(
    *,
    resource_id="i-123",
    field="instance_type",
    desired_value="t3.large",
):
    return GitOpsChange(
        resource_type="ec2",
        resource_id=resource_id,
        field=field,
        desired_value=desired_value,
        current_value="t3.medium",
        reason="Optimize underutilized instance",
    )


def make_change_set(*, requires_approval=True):
    return GitOpsEngine().create_change_set(
        source_action_id="action-1",
        changes=[make_change()],
        requires_approval=requires_approval,
    )


def test_change_validates_required_fields():
    change = make_change()

    assert change.resource_type == "ec2"
    assert change.resource_id == "i-123"
    assert change.field == "instance_type"
    assert change.desired_value == "t3.large"


def test_empty_resource_type_rejected():
    try:
        GitOpsChange(
            resource_type="",
            resource_id="i-123",
            field="instance_type",
            desired_value="t3.large",
        )
    except ValueError as exc:
        assert str(exc) == "resource_type cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_resource_id_rejected():
    try:
        GitOpsChange(
            resource_type="ec2",
            resource_id="",
            field="instance_type",
            desired_value="t3.large",
        )
    except ValueError as exc:
        assert str(exc) == "resource_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_empty_field_rejected():
    try:
        GitOpsChange(
            resource_type="ec2",
            resource_id="i-123",
            field="",
            desired_value="t3.large",
        )
    except ValueError as exc:
        assert str(exc) == "field cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_change_set_requires_changes():
    try:
        GitOpsEngine().create_change_set(
            source_action_id="action-1",
            changes=[],
        )
    except ValueError as exc:
        assert str(exc) == "changes cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_change_set_is_pending_approval_by_default():
    change_set = make_change_set()

    assert change_set.status == GitOpsChangeStatus.PENDING_APPROVAL
    assert change_set.requires_approval is True
    assert change_set.change_count == 1


def test_change_id_is_deterministic():
    first = make_change_set()
    second = make_change_set()

    assert first.change_id == second.change_id


def test_different_changes_produce_different_change_ids():
    first = make_change_set()

    second = GitOpsEngine().create_change_set(
        source_action_id="action-1",
        changes=[
            make_change(desired_value="t3.xlarge"),
        ],
    )

    assert first.change_id != second.change_id


def test_manifest_is_serializable_structure():
    change_set = make_change_set()

    manifest = change_set.to_manifest()

    assert manifest["change_id"] == change_set.change_id
    assert manifest["source_action_id"] == "action-1"
    assert manifest["status"] == "pending_approval"
    assert len(manifest["changes"]) == 1


def test_approval_moves_change_to_approved():
    change_set = make_change_set()

    GitOpsEngine().approve(change_set, "operator")

    assert change_set.status == GitOpsChangeStatus.APPROVED
    assert change_set.approved_by == "operator"


def test_empty_approver_rejected():
    change_set = make_change_set()

    try:
        GitOpsEngine().approve(change_set, "")
    except ValueError as exc:
        assert str(exc) == "approved_by cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_unapproved_change_cannot_apply():
    change_set = make_change_set()

    result = GitOpsEngine().apply(change_set)

    assert result.success is False
    assert result.applied_changes == 0
    assert "requires human approval" in result.message


def test_approved_change_can_dry_run():
    engine = GitOpsEngine()
    change_set = make_change_set()

    engine.approve(change_set, "operator")
    result = engine.apply(change_set)

    assert result.success is True
    assert result.dry_run is True
    assert result.status == GitOpsChangeStatus.APPLIED
    assert result.applied_changes == 1


def test_real_apply_is_disabled():
    engine = GitOpsEngine()
    change_set = make_change_set()

    engine.approve(change_set, "operator")
    result = engine.apply(change_set, dry_run=False)

    assert result.success is False
    assert result.dry_run is False
    assert "Real infrastructure mutation is disabled" in result.message


def test_rejected_change_cannot_apply():
    engine = GitOpsEngine()
    change_set = make_change_set()

    engine.reject(
        change_set,
        "operator",
        "Risk too high",
    )

    result = engine.apply(change_set)

    assert result.success is False
    assert change_set.status == GitOpsChangeStatus.REJECTED


def test_duplicate_changes_are_invalid():
    engine = GitOpsEngine()

    change_set = engine.create_change_set(
        source_action_id="action-1",
        changes=[
            make_change(),
            make_change(),
        ],
        requires_approval=False,
    )

    errors = engine.validate(change_set)

    assert len(errors) == 1
    assert "duplicate change target" in errors[0]


def test_verification_succeeds_for_matching_observed_value():
    engine = GitOpsEngine()
    change_set = make_change_set()

    engine.approve(change_set, "operator")
    result = engine.apply(change_set)

    assert result.success is True

    verified = engine.verify(
        change_set,
        observed_values={
            "ec2/i-123/instance_type": "t3.large",
        },
    )

    assert verified is True
    assert change_set.status == GitOpsChangeStatus.VERIFIED


def test_verification_fails_for_mismatched_observed_value():
    engine = GitOpsEngine()
    change_set = make_change_set()

    engine.approve(change_set, "operator")
    result = engine.apply(change_set)

    assert result.success is True

    verified = engine.verify(
        change_set,
        observed_values={
            "ec2/i-123/instance_type": "t3.medium",
        },
    )

    assert verified is False
    assert change_set.status == GitOpsChangeStatus.FAILED


def test_verification_requires_applied_state():
    change_set = make_change_set()

    try:
        GitOpsEngine().verify(change_set)
    except ValueError as exc:
        assert "Only applied GitOps changes can be verified" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_rejection_requires_reason():
    change_set = make_change_set()

    try:
        GitOpsEngine().reject(
            change_set,
            "operator",
            "",
        )
    except ValueError as exc:
        assert str(exc) == "rejection reason cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_no_approval_mode_can_dry_run_directly():
    engine = GitOpsEngine()

    change_set = make_change_set(requires_approval=False)

    assert change_set.status == GitOpsChangeStatus.PROPOSED

    result = engine.apply(change_set)

    assert result.success is True
    assert result.dry_run is True
    assert result.status == GitOpsChangeStatus.APPLIED
