import pytest

from autonomy.audit import AuditTrail


def record_event(trail, action_id="action-1", details=None, actor_id=None):
    return trail.record(
        action_id=action_id,
        action_type="scale",
        resource_type="instance",
        resource_id="i-123",
        old_status="running",
        new_status="stopped",
        event="action_completed",
        details=details or {"provider": "aws"},
        actor_id=actor_id,
    )


def test_empty_audit_trail_has_valid_integrity():
    assert AuditTrail().verify_integrity() is True


def test_recorded_events_have_valid_integrity():
    trail = AuditTrail()
    record_event(trail)
    record_event(trail, action_id="action-2")
    assert trail.verify_integrity() is True


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_record_rejects_non_finite_json_numbers_without_appending(value):
    trail = AuditTrail()

    with pytest.raises(ValueError):
        record_event(trail, details={"measurement": value})

    assert trail.get_events() == []
    assert trail.get_integrity_snapshot() == (True, 0)


def test_actor_attribution_is_recorded_and_covered_by_integrity_hash():
    trail = AuditTrail()
    event = record_event(trail, actor_id="user-17")
    assert event.actor_id == "user-17"
    assert trail.verify_integrity() is True

    trail._events[0] = event.__class__(**{**event.__dict__, "actor_id": "user-18"})
    assert trail.verify_integrity() is False


def test_actor_id_defaults_to_none_and_blank_values_are_rejected():
    trail = AuditTrail()
    assert record_event(trail).actor_id is None
    with pytest.raises(ValueError, match="actor_id"):
        record_event(trail, actor_id=" \t ")


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


def test_details_mutation_on_record_result_does_not_change_stored_event():
    trail = AuditTrail()
    event = record_event(trail, details={"provider": "aws"})
    event.details["provider"] = "unknown"
    assert trail.get_events()[0].details == {"provider": "aws"}
    assert trail.verify_integrity() is True


def test_input_and_returned_nested_details_are_isolated():
    trail = AuditTrail()
    nested = {"labels": ["original"], "metadata": {"region": "west"}}
    event = record_event(trail, details=nested)

    nested["metadata"]["region"] = "east"
    nested["labels"].append("input mutation")
    event.details["metadata"]["region"] = "north"
    event.details["labels"].append("return mutation")

    stored = trail.get_events()[0]
    assert stored.details == {
        "labels": ["original"],
        "metadata": {"region": "west"},
    }
    assert trail.verify_integrity() is True


def test_get_events_calls_return_independent_nested_snapshots():
    trail = AuditTrail()
    record_event(trail, details={"nested": {"items": [1, {"value": "original"}]}})

    first = trail.get_events()
    second = trail.get_events()
    first[0].details["nested"]["items"][1]["value"] = "changed"
    first[0].details["nested"]["items"].append(2)

    assert second[0].details == {"nested": {"items": [1, {"value": "original"}]}}
    assert trail.get_events()[0].details == second[0].details
    assert trail.verify_integrity() is True


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

def test_integrity_snapshot_returns_validity_and_count_atomically():
    trail = AuditTrail()
    record_event(trail)
    record_event(trail, action_id="action-2")

    assert trail.get_integrity_snapshot() == (True, 2)


def test_integrity_snapshot_reports_tampering_and_count():
    trail = AuditTrail()
    event = record_event(trail)
    event.details["tampered"] = True

    assert trail.get_integrity_snapshot() == (True, 1)


def test_empty_integrity_snapshot():
    assert AuditTrail().get_integrity_snapshot() == (True, 0)


def test_integrity_diagnostics_report_valid_empty_and_multiple_event_trails():
    trail = AuditTrail()
    assert trail.get_integrity_diagnostics().valid is True
    assert trail.get_integrity_diagnostics().event_count == 0
    assert trail.get_integrity_diagnostics().first_invalid_index is None

    record_event(trail)
    record_event(trail, action_id="action-2")
    assert trail.get_integrity_diagnostics().valid is True
    assert trail.get_integrity_diagnostics().event_count == 2
    assert trail.get_integrity_diagnostics().first_invalid_index is None


@pytest.mark.parametrize("tampered_index", [0, 1, 2])
def test_integrity_diagnostics_identify_first_tampered_event(tampered_index):
    trail = AuditTrail()
    for index in range(3):
        record_event(trail, action_id=f"action-{index}")
    event = trail._events[tampered_index]
    trail._events[tampered_index] = event.__class__(
        **{**event.__dict__, "event": "tampered"}
    )

    result = trail.get_integrity_diagnostics()
    assert (result.valid, result.event_count, result.first_invalid_index) == (
        False, 3, tampered_index
    )


def test_integrity_diagnostics_identify_stored_hash_tampering():
    trail = AuditTrail()
    record_event(trail)
    record_event(trail, action_id="action-2")
    trail._event_hashes[1] = "0" * 64

    assert trail.get_integrity_diagnostics().first_invalid_index == 1


def test_integrity_diagnostics_identify_missing_and_unexpected_hash_indices():
    missing = AuditTrail()
    record_event(missing)
    record_event(missing, action_id="action-2")
    missing._event_hashes.pop()
    assert missing.get_integrity_diagnostics().first_invalid_index == 1

    unexpected = AuditTrail()
    record_event(unexpected)
    unexpected._event_hashes.append("0" * 64)
    assert unexpected.get_integrity_diagnostics().first_invalid_index == 1


def test_integrity_diagnostics_identify_unserializable_event_content():
    trail = AuditTrail()
    record_event(trail)
    trail._events[0].details["bad"] = object()
    result = trail.get_integrity_diagnostics()
    assert result.valid is False
    assert result.first_invalid_index == 0


def test_integrity_verification_safely_rejects_event_with_missing_field():
    trail = AuditTrail()
    record_event(trail)
    del trail._events[0].__dict__["event"]
    event_state = dict(trail._events[0].__dict__)
    hashes = list(trail._event_hashes)

    result = trail.get_integrity_diagnostics()

    assert (result.valid, result.first_invalid_index) == (False, 0)
    assert trail._events[0].__dict__ == event_state
    assert trail._event_hashes == hashes


@pytest.mark.parametrize("stored_hash", [None, b"0" * 64, "é" * 64, "0" * 63, "g" * 64])
def test_integrity_verification_safely_rejects_malformed_hash(stored_hash):
    trail = AuditTrail()
    record_event(trail)
    trail._event_hashes[0] = stored_hash
    event = trail._events[0]
    event_state = dict(event.__dict__)

    result = trail.get_integrity_diagnostics()

    assert (result.valid, result.first_invalid_index) == (False, 0)
    assert trail._events[0] is event
    assert trail._events[0].__dict__ == event_state
    assert trail._event_hashes == [stored_hash]

def test_concurrent_recording_preserves_audit_integrity():
    from concurrent.futures import ThreadPoolExecutor

    trail = AuditTrail()
    total_events = 200

    def record(index):
        return trail.record(
            action_id=f"concurrent-{index}",
            action_type="scale",
            resource_type="instance",
            resource_id=f"i-{index}",
            old_status="running",
            new_status="stopped",
            event="action_completed",
            details={"sequence": index},
        )

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(record, range(total_events)))

    assert len(results) == total_events
    assert len(trail.get_events()) == total_events
    assert trail.get_integrity_snapshot() == (True, total_events)


def test_concurrent_recording_and_integrity_snapshots_remain_consistent():
    from concurrent.futures import ThreadPoolExecutor

    trail = AuditTrail()
    total_events = 150

    def record(index):
        return trail.record(
            action_id=f"parallel-{index}",
            action_type="scale",
            resource_type="instance",
            resource_id=f"i-{index}",
            old_status="running",
            new_status="stopped",
            event="action_completed",
            details={"sequence": index},
        )

    def snapshot(_):
        return trail.get_integrity_snapshot()

    with ThreadPoolExecutor(max_workers=12) as executor:
        recording = [executor.submit(record, i) for i in range(total_events)]
        checking = [executor.submit(snapshot, i) for i in range(40)]

        for future in recording:
            future.result()

        snapshots = [future.result() for future in checking]

    assert all(valid is True for valid, _ in snapshots)
    assert all(0 <= count <= total_events for _, count in snapshots)
    assert trail.get_integrity_snapshot() == (True, total_events)
    assert len(trail.get_events()) == total_events

def test_stored_hash_mutation_is_detected():
    trail = AuditTrail()
    record_event(trail)

    original_hash = trail._event_hashes[0]
    trail._event_hashes[0] = "0" * 64

    assert trail.verify_integrity() is False

    trail._event_hashes[0] = original_hash
    assert trail.verify_integrity() is True


def test_reordering_events_and_hashes_is_detected():
    trail = AuditTrail()
    record_event(trail, action_id="first")
    record_event(trail, action_id="second")

    trail._events.reverse()
    trail._event_hashes.reverse()

    assert trail.verify_integrity() is False


def test_deleting_event_and_matching_hash_from_middle_is_detected():
    trail = AuditTrail()
    for index in range(3):
        record_event(trail, action_id=f"action-{index}")

    del trail._events[1]
    del trail._event_hashes[1]

    assert trail.verify_integrity() is False


def test_appending_event_without_hash_is_detected():
    trail = AuditTrail()
    record_event(trail)

    original = trail._events[0]
    forged = original.__class__(
        **{
            **original.__dict__,
            "action_id": "forged-action",
        }
    )
    trail._events.append(forged)

    assert trail.verify_integrity() is False


def test_appending_hash_without_event_is_detected():
    trail = AuditTrail()
    record_event(trail)

    trail._event_hashes.append("f" * 64)

    assert trail.verify_integrity() is False


@pytest.mark.parametrize("malformed_event", [None, {"event": "action_completed"}])
def test_integrity_verification_safely_rejects_malformed_event_records(malformed_event):
    trail = AuditTrail()
    record_event(trail)
    trail._events[0] = malformed_event
    hashes = list(trail._event_hashes)

    result = trail.get_integrity_diagnostics()

    assert (result.valid, result.event_count, result.first_invalid_index) == (
        False, 1, 0
    )
    assert trail._events == [malformed_event]
    assert trail._event_hashes == hashes
