from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any


class MemoryOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class OperationalMemory:
    memory_id: str
    resource_id: str
    resource_type: str
    situation: str
    action: str
    outcome: MemoryOutcome
    lesson: str
    metadata: dict[str, Any] = field(default_factory=dict)


class OperationalMemoryStore:
    """In-memory operational experience store for future decision support."""

    def __init__(self) -> None:
        self._memories: list[OperationalMemory] = []
        self._lock = Lock()

    def remember(
        self,
        *,
        memory_id: str,
        resource_id: str,
        resource_type: str,
        situation: str,
        action: str,
        outcome: MemoryOutcome,
        lesson: str,
        metadata: dict[str, Any] | None = None,
    ) -> OperationalMemory:
        for value, name in (
            (memory_id, "memory_id"),
            (resource_id, "resource_id"),
            (resource_type, "resource_type"),
            (situation, "situation"),
            (action, "action"),
            (lesson, "lesson"),
        ):
            if not value or not value.strip():
                raise ValueError(f"{name} cannot be empty")

        memory = OperationalMemory(
            memory_id=memory_id,
            resource_id=resource_id,
            resource_type=resource_type,
            situation=situation,
            action=action,
            outcome=outcome,
            lesson=lesson,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._memories.append(memory)

        return memory

    def get(self, memory_id: str) -> OperationalMemory | None:
        with self._lock:
            for memory in self._memories:
                if memory.memory_id == memory_id:
                    return memory
        return None

    def all(self) -> list[OperationalMemory]:
        with self._lock:
            return list(self._memories)

    def find_similar(
        self,
        *,
        resource_type: str | None = None,
        situation: str | None = None,
        action: str | None = None,
        outcome: MemoryOutcome | None = None,
    ) -> list[OperationalMemory]:
        with self._lock:
            memories = list(self._memories)

        results: list[OperationalMemory] = []

        for memory in memories:
            if resource_type and memory.resource_type != resource_type:
                continue
            if situation and situation.lower() not in memory.situation.lower():
                continue
            if action and memory.action != action:
                continue
            if outcome and memory.outcome != outcome:
                continue

            results.append(memory)

        return results

    def lessons_for(
        self,
        *,
        resource_type: str,
        situation: str,
    ) -> list[str]:
        memories = self.find_similar(
            resource_type=resource_type,
            situation=situation,
        )

        return [memory.lesson for memory in memories]

    def clear(self) -> None:
        with self._lock:
            self._memories.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._memories)
