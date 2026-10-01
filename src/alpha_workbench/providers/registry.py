"""Provider construction and name-based lookup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .contracts import ProviderCapability, ProviderCatalogEntry
from .protocols import ProviderAdapter


class ProviderRegistry:
    def __init__(
        self,
        providers: tuple[ProviderAdapter, ...] = (),
        catalog: tuple[ProviderCatalogEntry, ...] = (),
    ) -> None:
        self._providers: dict[str, ProviderAdapter] = {}
        self._catalog = {entry.capability.provider_id: entry for entry in catalog}
        for provider in providers:
            self.register(provider)
            if provider.capability.provider_id not in self._catalog:
                self._catalog[provider.capability.provider_id] = ProviderCatalogEntry(
                    capability=provider.capability,
                    configured=True,
                )

    @classmethod
    def from_config(cls, config_path: Path | str | None = None) -> ProviderRegistry:
        path = Path(config_path) if config_path is not None else _default_config_path("")
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"provider config {path} must contain a mapping")
        providers: list[ProviderAdapter] = []
        entries: list[ProviderCatalogEntry] = []
        for provider_id, config in raw.items():
            if not isinstance(provider_id, str) or not isinstance(config, dict):
                continue
            capability_data = config.get("capability")
            if not isinstance(capability_data, dict):
                raise ValueError(f"provider {provider_id!r} is missing capability metadata")
            capability = ProviderCapability(provider_id=provider_id, **capability_data)
            env_name = config.get("credentials_env")
            if env_name is not None and not isinstance(env_name, str):
                raise ValueError(f"provider {provider_id!r} has invalid credentials_env")
            requires_credentials = bool(config.get("requires_credentials", False))
            configured = not requires_credentials or bool(env_name and os.environ.get(env_name))
            entries.append(
                ProviderCatalogEntry(
                    capability=capability,
                    configured=configured,
                    credentials_env=env_name,
                    limitation=str(config.get("limitation", "")),
                )
            )
            if configured:
                providers.append(build_provider(provider_id, config_path=path))
        return cls(tuple(providers), tuple(entries))

    def register(self, provider: ProviderAdapter) -> None:
        provider_id = provider.capability.provider_id
        if provider_id in self._providers:
            raise ValueError(f"provider {provider_id!r} is already registered")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise KeyError(f"unknown provider {provider_id!r}") from error

    def list_capabilities(self) -> tuple[object, ...]:
        return tuple(entry.capability for entry in self._catalog.values())

    def list_catalog(self) -> tuple[ProviderCatalogEntry, ...]:
        return tuple(self._catalog.values())

    @property
    def configured_provider_ids(self) -> tuple[str, ...]:
        return tuple(self._providers)


def build_provider(provider_id: str, *, config_path: Path | str | None = None) -> ProviderAdapter:
    """Build one configured provider. Secret values are resolved only from env vars."""

    path = Path(config_path) if config_path is not None else _default_config_path(provider_id)
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"provider config {path} must contain a mapping")
    config = raw.get(provider_id)
    if not isinstance(config, dict):
        raise ValueError(f"provider {provider_id!r} is not configured in {path}")
    kind = config.get("kind")
    if kind == "openfigi":
        from .openfigi import OpenFigiAdapter

        return OpenFigiAdapter.from_config(config)
    if kind == "eodhd":
        from .eodhd import EodhdAdapter

        return EodhdAdapter.from_config(config)
    if kind == "alpha_vantage_compat":
        from .alpha_vantage_compat import AlphaVantageCompatibilityAdapter

        return AlphaVantageCompatibilityAdapter.from_config(config)
    raise ValueError(f"provider {provider_id!r} has unsupported kind {kind!r}")


def _default_config_path(provider_id: str) -> Path:
    del provider_id
    return Path(__file__).resolve().parents[3] / "config" / "providers" / "catalog.yaml"
