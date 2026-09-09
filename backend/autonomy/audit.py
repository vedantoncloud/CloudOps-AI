from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    action_id: str
    action_type: str
    resource_type: str
    resource_id: str
    old_status: str
    new_status: str
    event: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict[str, Any] = field(default_factory=dict)


class AuditTrail:
    """In-memory audit trail for autonomous action lifecycle events."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = Lock()

    def record(
        self,
        *,
        action_id: str,
        action_type: str,
        resource_type: str,
        resource_id: str,
        old_status: str,
        new_status: str,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        if not action_id or not action_id.strip():
            raise ValueError("action_id cannot be empty")

        if not action_type or not action_type.strip():
            raise ValueError("action_type cannot be empty")

        if not resource_type or not resource_type.strip():
            raise ValueError("resource_type cannot be empty")

        if not resource_id or not resource_id.strip():
            raise ValueError("resource_id cannot be empty")

        if not event or not event.strip():
            raise ValueError("event cannot be empty")

        audit_event = AuditEvent(
            action_id=action_id,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            old_status=old_status,
            new_status=new_status,
            event=event,
            details=details or {},
        )

        with self._lock:
            self._events.append(audit_event)

        return audit_event

    def get_events(self, action_id: str | None = None) -> list[AuditEvent]:
        with self._lock:
            events = list(self._events)

        if action_id is None:
            return events

        return [
            event
            for event in events
            if event.action_id == action_id
        ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
