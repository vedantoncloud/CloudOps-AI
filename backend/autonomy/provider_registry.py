from threading import RLock

from autonomy.provider import CloudProvider


class ProviderRegistry:
    """Thread-safe registry for cloud provider adapters."""

    def __init__(self) -> None:
        self._providers: dict[str, CloudProvider] = {}
        self._lock = RLock()

    @staticmethod
    def _normalize(name: str) -> str:
        normalized = name.strip().lower()

        if not normalized:
            raise ValueError("provider name cannot be empty")

        return normalized

    def register(self, provider: CloudProvider) -> CloudProvider:
        name = self._normalize(provider.provider_name)

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

    def unregister(self, name: str) -> CloudProvider:
        normalized = self._normalize(name)

        with self._lock:
            if normalized not in self._providers:
                raise KeyError(
                    f"unknown cloud provider: {normalized}"
                )

            return self._providers.pop(normalized)
