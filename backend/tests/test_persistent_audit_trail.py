import sqlite3

import pytest

from autonomy.persistent_audit_trail import PersistentAuditTrail


def record(trail, action_id="action-1"):
    return trail.record(
        action_id=action_id,
        action_type="review_instance_state",
        resource_type="ec2",
        resource_id="i-123",
        old_status="approved",
        new_status="executing",
        event="execution_started",
        details={"nested": {"value": 1}},
        actor_id="operator-1",
    )


def test_events_and_hash_chain_survive_reopening_database(tmp_path):
    database = tmp_path / "events.db"
    first = PersistentAuditTrail(database)
    record(first)
    record(first, "action-2")

    reopened = PersistentAuditTrail(database)
    assert [event.action_id for event in reopened.get_events()] == [
        "action-1",
        "action-2",
    ]
    assert reopened.get_integrity_diagnostics().valid
    assert reopened.get_integrity_diagnostics().event_count == 2
    assert reopened.get_integrity_snapshot() == (True, 2)
    assert reopened.verify_integrity()
    assert reopened.get_events("action-2")[0].actor_id == "operator-1"


def test_invalid_record_does_not_append_to_database(tmp_path):
    trail = PersistentAuditTrail(tmp_path / "events.db")
    with pytest.raises(ValueError, match="action_id cannot be empty"):
        trail.record(
            action_id=" ",
            action_type="review",
            resource_type="ec2",
            resource_id="i-123",
            old_status="approved",
            new_status="executing",
            event="started",
        )
    assert trail.get_events() == []
    assert trail.get_integrity_diagnostics().valid


def test_database_record_tampering_is_reported_at_first_bad_event(tmp_path):
    database = tmp_path / "events.db"
    trail = PersistentAuditTrail(database)
    record(trail)
    record(trail, "action-2")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_events SET event_hash = ? WHERE sequence = 2",
            ("0" * 64,),
        )

    result = PersistentAuditTrail(database).get_integrity_diagnostics()
    assert (result.valid, result.event_count, result.first_invalid_index) == (
        False,
        2,
        1,
    )


def test_clear_removes_persisted_events_and_resets_integrity(tmp_path):
    database = tmp_path / "events.db"
    trail = PersistentAuditTrail(database)
    record(trail)
    trail.clear()

    reopened = PersistentAuditTrail(database)
    assert reopened.get_events() == []
    assert reopened.get_integrity_diagnostics().valid
