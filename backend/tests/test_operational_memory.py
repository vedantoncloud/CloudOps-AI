from autonomy.operational_memory import (
    MemoryOutcome,
    OperationalMemoryStore,
)


def test_memory_can_be_stored():
    store = OperationalMemoryStore()

    memory = store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU utilization",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="CPU investigation resolved the issue.",
    )

    assert memory.memory_id == "mem-1"
    assert len(store) == 1


def test_memory_can_be_retrieved():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate CPU before scaling.",
    )

    result = store.get("mem-1")

    assert result is not None
    assert result.resource_id == "i-123"


def test_unknown_memory_returns_none():
    store = OperationalMemoryStore()

    assert store.get("missing") is None


def test_all_returns_copy_of_memories():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate first.",
    )

    memories = store.all()

    assert len(memories) == 1
    assert memories[0].memory_id == "mem-1"


def test_find_similar_by_resource_type():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Check CPU trend.",
    )

    store.remember(
        memory_id="mem-2",
        resource_id="bucket-1",
        resource_type="s3",
        situation="Large object",
        action="review_large_object",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Review object lifecycle.",
    )

    results = store.find_similar(resource_type="ec2")

    assert len(results) == 1
    assert results[0].memory_id == "mem-1"


def test_find_similar_by_situation():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU utilization",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate CPU before scaling.",
    )

    store.remember(
        memory_id="mem-2",
        resource_id="i-456",
        resource_type="ec2",
        situation="Network degradation",
        action="review_network",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Check network metrics.",
    )

    results = store.find_similar(
        resource_type="ec2",
        situation="cpu",
    )

    assert len(results) == 1
    assert results[0].memory_id == "mem-1"


def test_find_similar_by_action():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate first.",
    )

    results = store.find_similar(
        action="investigate_cpu_capacity",
    )

    assert len(results) == 1


def test_find_similar_by_outcome():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Action worked.",
    )

    store.remember(
        memory_id="mem-2",
        resource_id="i-456",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.FAILURE,
        lesson="Action failed.",
    )

    results = store.find_similar(
        outcome=MemoryOutcome.FAILURE,
    )

    assert len(results) == 1
    assert results[0].memory_id == "mem-2"


def test_lessons_for_returns_previous_lessons():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU utilization",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate CPU before scaling.",
    )

    store.remember(
        memory_id="mem-2",
        resource_id="i-456",
        resource_type="ec2",
        situation="High CPU utilization",
        action="review_cpu_utilization",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Check recent CPU trend.",
    )

    lessons = store.lessons_for(
        resource_type="ec2",
        situation="high cpu",
    )

    assert lessons == [
        "Investigate CPU before scaling.",
        "Check recent CPU trend.",
    ]


def test_metadata_is_preserved():
    store = OperationalMemoryStore()

    memory = store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate first.",
        metadata={"impact_score": 40},
    )

    assert memory.metadata["impact_score"] == 40


def test_metadata_is_copied():
    store = OperationalMemoryStore()
    metadata = {"impact_score": 40}

    memory = store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate first.",
        metadata=metadata,
    )

    metadata["impact_score"] = 100

    assert memory.metadata["impact_score"] == 40


def test_clear_removes_memories():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="CPU issue",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate first.",
    )

    store.clear()

    assert len(store) == 0
    assert store.all() == []


def test_empty_required_fields_are_rejected():
    store = OperationalMemoryStore()

    try:
        store.remember(
            memory_id="",
            resource_id="i-123",
            resource_type="ec2",
            situation="CPU issue",
            action="investigate_cpu_capacity",
            outcome=MemoryOutcome.SUCCESS,
            lesson="Investigate first.",
        )
    except ValueError as exc:
        assert str(exc) == "memory_id cannot be empty"
    else:
        raise AssertionError("Expected ValueError")


def test_multiple_filters_can_be_combined():
    store = OperationalMemoryStore()

    store.remember(
        memory_id="mem-1",
        resource_id="i-123",
        resource_type="ec2",
        situation="High CPU utilization",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
        lesson="Investigate CPU.",
    )

    store.remember(
        memory_id="mem-2",
        resource_id="i-456",
        resource_type="ec2",
        situation="High CPU utilization",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.FAILURE,
        lesson="Previous action failed.",
    )

    results = store.find_similar(
        resource_type="ec2",
        situation="cpu",
        action="investigate_cpu_capacity",
        outcome=MemoryOutcome.SUCCESS,
    )

    assert len(results) == 1
    assert results[0].memory_id == "mem-1"
