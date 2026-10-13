from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
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
    actor_id: str | None = None


@dataclass(frozen=True)
class AuditIntegrityResult:
    valid: bool
    event_count: int
    first_invalid_index: int | None


class AuditTrail:
    """In-memory audit trail with tamper-evident hash-chain verification."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._event_hashes: list[str] = []
        self._lock = Lock()

    @staticmethod
    def _canonical_event(event: AuditEvent) -> bytes:
        return json.dumps(
            asdict(event),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _calculate_hash(previous_hash: str, event: AuditEvent) -> str:
        digest = hashlib.sha256()
        digest.update(previous_hash.encode("ascii"))
        digest.update(b"\0")
        digest.update(AuditTrail._canonical_event(event))
        return digest.hexdigest()

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
        actor_id: str | None = None,
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
        if actor_id is not None and not actor_id.strip():
            raise ValueError("actor_id cannot be empty")

        audit_event = AuditEvent(
            action_id=action_id,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            old_status=old_status,
            new_status=new_status,
            event=event,
            details=details or {},
            actor_id=actor_id,
        )

        with self._lock:
            previous_hash = self._event_hashes[-1] if self._event_hashes else ""
            event_hash = self._calculate_hash(previous_hash, audit_event)
            self._events.append(audit_event)
            self._event_hashes.append(event_hash)

        return audit_event

    def get_events(self, action_id: str | None = None) -> list[AuditEvent]:
        with self._lock:
            events = list(self._events)

        if action_id is None:
            return events

        return [item for item in events if item.action_id == action_id]

    def _verify_integrity_unlocked(self) -> AuditIntegrityResult:
        event_count = len(self._events)
        if event_count != len(self._event_hashes):
            return AuditIntegrityResult(
                valid=False,
                event_count=event_count,
                first_invalid_index=min(event_count, len(self._event_hashes)),
            )

        previous_hash = ""
        for index, (event, stored_hash) in enumerate(zip(self._events, self._event_hashes)):
            try:
                expected_hash = self._calculate_hash(previous_hash, event)
            except Exception:
                return AuditIntegrityResult(False, event_count, index)

            if not isinstance(stored_hash, str) or not hmac.compare_digest(
                expected_hash, stored_hash
            ):
                return AuditIntegrityResult(False, event_count, index)

            previous_hash = stored_hash

        return AuditIntegrityResult(True, event_count, None)

    def verify_integrity(self) -> bool:
        """Return False if an event, its details, or chain metadata was altered."""
        with self._lock:
            return self._verify_integrity_unlocked().valid

    def get_integrity_snapshot(self) -> tuple[bool, int]:
        """Return integrity status and event count from one atomic snapshot."""
        with self._lock:
            result = self._verify_integrity_unlocked()
            return result.valid, result.event_count

    def get_integrity_diagnostics(self) -> AuditIntegrityResult:
        """Return safe integrity diagnostics from one atomic snapshot."""
        with self._lock:
            return self._verify_integrity_unlocked()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._event_hashes.clear()
