from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from autonomy.persistent_audit_health import PersistentAuditHealthChecker
from autonomy.persistent_audit_idempotency import PersistentAuditIdempotencyStore


@dataclass(frozen=True)
class AuditReconciliationItem:
    run_id: str
    event_type: str
    status: str
    claimed_at: float
    age_seconds: float
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditReconciliationResult:
    items: tuple[AuditReconciliationItem, ...]
    stale_count: int
    active_count: int
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.items)


class PersistentAuditReconciliation:
    """Read-only reconciliation boundary for pending persistent audit claims."""

    def __init__(
        self,
        store: PersistentAuditIdempotencyStore,
        *,
        lease_seconds: float = 300.0,
        now: datetime | None = None,
    ) -> None:
        if lease_seconds < 0:
            raise ValueError("lease_seconds must be non-negative")
        self.store = store
        self.lease_seconds = float(lease_seconds)
        self._now = now

    def inspect(self) -> AuditReconciliationResult:
        now = self._current_timestamp()
        pending = PersistentAuditHealthChecker(self.store.path).list_pending()

        items: list[AuditReconciliationItem] = []
        stale_count = 0
        active_count = 0

        for claim in pending:
            run_id = str(claim.get("run_id", "")).strip()
            event_type = str(claim.get("event_type", "")).strip()
            if not run_id:
                raise ValueError("pending claim is missing run_id")
            if not event_type:
                raise ValueError("pending claim is missing event_type")

            claimed_at = self._parse_claimed_at(claim.get("claimed_at"))
            age_seconds = max(0.0, now - claimed_at)
            status = "stale" if age_seconds >= self.lease_seconds else "active"

            if status == "stale":
                stale_count += 1
            else:
                active_count += 1

            raw_evidence = claim.get("evidence", {})
            normalized_evidence = (
                dict(raw_evidence)
                if isinstance(raw_evidence, dict)
                else {"raw": raw_evidence}
            )

            items.append(
                AuditReconciliationItem(
                    run_id=run_id,
                    event_type=event_type,
                    status=status,
                    claimed_at=claimed_at,
                    age_seconds=age_seconds,
                    evidence=normalized_evidence,
                )
            )

        evidence = {
            "store": "sqlite",
            "read_only": True,
            "lease_seconds": self.lease_seconds,
            "pending_count": len(items),
            "active_count": active_count,
            "stale_count": stale_count,
        }

        return AuditReconciliationResult(
            items=tuple(items),
            stale_count=stale_count,
            active_count=active_count,
            evidence=evidence,
        )

    def _current_timestamp(self) -> float:
        value = self._now
        if value is None:
            return datetime.now(timezone.utc).timestamp()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).timestamp()

    @staticmethod
    def _parse_claimed_at(value: Any) -> float:
        try:
            timestamp = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid claimed_at timestamp") from exc
        if timestamp < 0:
            raise ValueError("invalid claimed_at timestamp")
        return timestamp
