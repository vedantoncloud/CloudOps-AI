import pytest

from autonomy.audit import AuditTrail


def record_event(trail, action_id="action-1", details=None):
    return trail.record(
        action_id=action_id,
        action_type="scale",
        resource_type="instance",
        resource_id="i-123",
        old_status="running",
        new_status="stopped",
        event="action_completed",
        details=details or {"provider": "aws"},
    )


def test_empty_audit_trail_has_valid_integrity():
    assert AuditTrail().verify_integrity() is True


def test_recorded_events_have_valid_integrity():
    trail = AuditTrail()
    record_event(trail)
    record_event(trail, action_id="action-2")
    assert trail.verify_integrity() is True


def test_event_field_tampering_is_detected():
    trail = AuditTrail()
    record_event(trail)
    trail._events[0] = trail._events[0].__class__(
        **{
            **trail._events[0].__dict__,
            "new_status": "deleted",
        }
    )
    assert trail.verify_integrity() is False


def test_details_mutation_is_detected():
    trail = AuditTrail()
    event = record_event(trail, details={"provider": "aws"})
    event.details["provider"] = "unknown"
    assert trail.verify_integrity() is False


def test_tampering_with_earlier_event_breaks_following_chain():
    trail = AuditTrail()
    record_event(trail, action_id="first")
    record_event(trail, action_id="second")
    original = trail._events[0]
    trail._events[0] = original.__class__(
        **{**original.__dict__, "event": "modified"}
    )
    assert trail.verify_integrity() is False


def test_clear_resets_events_and_integrity_chain():
    trail = AuditTrail()
    record_event(trail)
    trail.clear()
    assert trail.get_events() == []
    assert trail.verify_integrity() is True


def test_existing_action_id_filter_remains_compatible():
    trail = AuditTrail()
    record_event(trail, action_id="first")
    record_event(trail, action_id="second")
    assert [item.action_id for item in trail.get_events("second")] == ["second"]
    assert trail.verify_integrity() is True


def test_hash_count_mismatch_is_detected():
    trail = AuditTrail()
    record_event(trail)
    trail._event_hashes.clear()
    assert trail.verify_integrity() is False
