from autonomy.audit import AuditTrail


def test_record_creates_audit_event():
    audit = AuditTrail()

    event = audit.record(
        action_id="act-123",
        action_type="investigate_cpu_capacity",
        resource_type="ec2",
        resource_id="i-123",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    assert event.action_id == "act-123"
    assert event.action_type == "investigate_cpu_capacity"
    assert event.resource_type == "ec2"
    assert event.resource_id == "i-123"
    assert event.old_status == "approved"
    assert event.new_status == "executing"
    assert event.event == "execution_started"
    assert event.timestamp
    assert event.details == {}


def test_get_events_returns_all_events():
    audit = AuditTrail()

    audit.record(
        action_id="act-1",
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-1",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    audit.record(
        action_id="act-2",
        action_type="review_bucket_usage",
        resource_type="s3",
        resource_id="bucket-1",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    events = audit.get_events()

    assert len(events) == 2


def test_get_events_filters_by_action_id():
    audit = AuditTrail()

    audit.record(
        action_id="act-1",
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-1",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    audit.record(
        action_id="act-2",
        action_type="review_bucket_usage",
        resource_type="s3",
        resource_id="bucket-1",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    events = audit.get_events("act-1")

    assert len(events) == 1
    assert events[0].action_id == "act-1"


def test_record_preserves_details():
    audit = AuditTrail()

    event = audit.record(
        action_id="act-123",
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-123",
        old_status="executing",
        new_status="succeeded",
        event="execution_verified",
        details={
            "dry_run": True,
            "executed": False,
        },
    )

    assert event.details == {
        "dry_run": True,
        "executed": False,
    }


def test_empty_action_id_is_rejected():
    audit = AuditTrail()

    try:
        audit.record(
            action_id="",
            action_type="review_instance_state",
            resource_type="ec2",
            resource_id="i-123",
            old_status="approved",
            new_status="executing",
            event="execution_started",
        )
        assert False
    except ValueError as exc:
        assert str(exc) == "action_id cannot be empty"


def test_empty_event_is_rejected():
    audit = AuditTrail()

    try:
        audit.record(
            action_id="act-123",
            action_type="review_instance_state",
            resource_type="ec2",
            resource_id="i-123",
            old_status="approved",
            new_status="executing",
            event="",
        )
        assert False
    except ValueError as exc:
        assert str(exc) == "event cannot be empty"


def test_clear_removes_all_events():
    audit = AuditTrail()

    audit.record(
        action_id="act-123",
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-123",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    assert len(audit.get_events()) == 1

    audit.clear()

    assert audit.get_events() == []


def test_events_are_returned_as_a_copy():
    audit = AuditTrail()

    audit.record(
        action_id="act-123",
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-123",
        old_status="approved",
        new_status="executing",
        event="execution_started",
    )

    events = audit.get_events()
    events.clear()

    assert len(audit.get_events()) == 1
