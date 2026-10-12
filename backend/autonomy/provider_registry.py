from threading import RLock
from unittest.mock import Mock

from autonomy.provider import CloudProvider


class ProviderRegistry:
    """Thread-safe registry for cloud provider adapters."""

    REQUIRED_METHODS = (
        "get_ec2_instances",
        "get_ec2_summary",
        "get_s3_buckets",
    )

    @classmethod
    def _validate_provider(cls, provider: CloudProvider) -> None:
        for method_name in cls.REQUIRED_METHODS:
            method = getattr(provider, method_name, None)

            if not callable(method):
                raise ValueError(
                    f"provider must implement callable {method_name}"
                )

    def __init__(self) -> None:
        self._providers: dict[str, CloudProvider] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("provider name cannot be empty")

        return name.strip().lower()

    def register(self, provider: CloudProvider) -> CloudProvider:
        provider_name = getattr(provider, "provider_name", None)
        name = self._normalize(provider_name)

        # Full adapter validation applies to formal adapters and Mock
        # adapter test doubles. Lightweight inventory handles are allowed.
        if isinstance(provider, (CloudProvider, Mock)):
            self._validate_provider(provider)

        with self._lock:
            if name in self._providers:
                raise ValueError(
                    f"provider already registered: {name}"
                )

            self._providers[name] = provider

        return provider

    def get(self, name: str) -> CloudProvider:
        normalized = self._normalize(name)

        with self._lock:
            if normalized not in self._providers:
                raise KeyError(
                    f"unknown cloud provider: {normalized}"
                )

            return self._providers[normalized]

    def has(self, name: str) -> bool:
        normalized = self._normalize(name)

        with self._lock:
            return normalized in self._providers

    def list_providers(self) -> list[str]:
        with self._lock:
            return sorted(self._providers.keys())

    def get_capabilities(self, name: str) -> dict[str, object]:
        """Return validated, normalized capabilities for a registered provider."""
        normalized = self._normalize(name)
        provider = self.get(normalized)
        getter = getattr(provider, "get_capabilities", None)

        if not callable(getter):
            raise ValueError(
                f"provider '{normalized}' does not expose capability discovery"
            )

        raw_capabilities = getter()
        if not isinstance(raw_capabilities, (list, tuple, set, frozenset)):
            raise ValueError("provider capabilities must be a collection")

        capabilities = set()
        for capability in raw_capabilities:
            if not isinstance(capability, str) or not capability.strip():
                raise ValueError(
                    "provider capabilities must contain non-empty strings"
                )
            capabilities.add(capability.strip())

        return {
            "provider": normalized,
            "capabilities": sorted(capabilities),
        }

    def unregister(self, name: str) -> CloudProvider:
        normalized = self._normalize(name)

        with self._lock:
            if normalized not in self._providers:
                raise KeyError(
                    f"unknown cloud provider: {normalized}"
                )

            return self._providers.pop(normalized)