from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autonomy.resource_observer import ResourceObservation


class ResourcePolicyDecision(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


@dataclass(frozen=True)
class ResourcePolicy:
    """Declarative governance policy for discovered resources."""

    allowed_providers: set[str] = field(default_factory=lambda: {"aws"})
    allowed_resource_types: set[str] = field(
        default_factory=lambda: {"ec2", "s3"}
    )
    require_read_only: bool = True
    required_metadata: set[str] = field(default_factory=set)
    denied_tag_values: dict[str, set[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourcePolicyResult:
    decision: ResourcePolicyDecision
    reasons: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)


class ResourcePolicyEngine:
    """Evaluate normalized resource observations against governance policy."""

    def __init__(self, policy: ResourcePolicy | None = None) -> None:
        self.policy = policy if policy is not None else ResourcePolicy()

    def evaluate(self, observation: ResourceObservation) -> ResourcePolicyResult:
        reasons: list[str] = []
        evidence: dict[str, Any] = {
            "provider": observation.provider,
            "resource_type": observation.resource_type,
            "resource_id": observation.resource_id,
            "read_only": observation.read_only,
        }

        provider_allowed = (
            observation.provider.lower() in
            {item.lower() for item in self.policy.allowed_providers}
        )
        type_allowed = (
            observation.resource_type.lower() in
            {item.lower() for item in self.policy.allowed_resource_types}
        )

        if not provider_allowed:
            reasons.append(
                f"Provider '{observation.provider}' is not allowed by resource policy."
            )

        if not type_allowed:
            reasons.append(
                f"Resource type '{observation.resource_type}' is not allowed by resource policy."
            )

        if self.policy.require_read_only and not observation.read_only:
            reasons.append("Resource observation is not read-only.")

        missing_metadata = sorted(
            key
            for key in self.policy.required_metadata
            if key not in observation.data.get("metadata", {})
        )
        if missing_metadata:
            reasons.append(
                "Required resource metadata is missing: "
                + ", ".join(missing_metadata)
            )

        tags = observation.data.get("tags", {})
        if not isinstance(tags, dict):
            tags = {}

        denied_tags: dict[str, str] = {}
        for key, denied_values in self.policy.denied_tag_values.items():
            if key in tags and str(tags[key]) in {str(value) for value in denied_values}:
                denied_tags[key] = str(tags[key])

        if denied_tags:
            reasons.append("Resource contains a denied tag value.")

        evidence["provider_allowed"] = provider_allowed
        evidence["resource_type_allowed"] = type_allowed
        evidence["missing_metadata"] = missing_metadata
        evidence["denied_tags"] = denied_tags

        if not provider_allowed or not type_allowed or denied_tags:
            decision = ResourcePolicyDecision.DENY
        elif self.policy.require_read_only and not observation.read_only:
            decision = ResourcePolicyDecision.DENY
        elif missing_metadata:
            decision = ResourcePolicyDecision.REVIEW
        else:
            decision = ResourcePolicyDecision.ALLOW

        if not reasons:
            reasons.append("Resource satisfies the configured governance policy.")

        return ResourcePolicyResult(
            decision=decision,
            reasons=reasons,
            evidence=evidence,
        )
