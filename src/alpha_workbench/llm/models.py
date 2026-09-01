"""The single model-provider boundary used by all product agents.

Agents depend on ``LLMClient`` rather than a vendor SDK. Switching a role from
OpenAI to Anthropic, Gemini, or Vertex changes ``config/models.yaml`` only.
Cloud calls are deliberately unavailable unless the optional ``agents`` extra
and the configured environment variable are present.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """Provider configuration for one named agent role."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)


class LLMClient(Protocol):
    """Small typed boundary that keeps agents independent of model vendors."""

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Return one JSON object matching the caller's documented contract."""


class FakeLLMClient:
    """Deterministic, key-free client for tests and offline skeleton runs."""

    def __init__(self, response: Mapping[str, Any] | None = None) -> None:
        self._response = dict(response or {"action": "complete", "reason": "offline fake"})

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        del system, user
        return dict(self._response)


class LiteLLMClient:
    """Lazy LiteLLM adapter; imported only for an explicitly configured cloud call."""

    def __init__(self, config: ModelConfig, api_key: str) -> None:
        self._config = config
        self._api_key = api_key

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        try:
            from litellm import completion
        except ImportError as error:  # pragma: no cover - exercised by user setup
            raise RuntimeError(
                "Install the project with the [agents] extra to use cloud models"
            ) from error
        response = completion(
            model=self._config.model,
            api_key=self._api_key,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise RuntimeError("model returned no JSON content")
        decoded = json.loads(content)
        if not isinstance(decoded, dict):
            raise RuntimeError("model JSON response must be an object")
        return decoded


def load_model_config(path: Path, role: str) -> ModelConfig:
    """Read one role from the tracked, credential-free YAML configuration."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("roles"), dict):
        raise ValueError("models config must contain a roles mapping")
    role_config = raw["roles"].get(role)
    if not isinstance(role_config, dict):
        raise ValueError(f"no model configuration exists for role {role!r}")
    return ModelConfig.model_validate(role_config)


def create_llm(config: ModelConfig) -> LLMClient:
    """Create the configured client. This is the only provider switch point."""

    if config.provider == "fake":
        return FakeLLMClient()
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise RuntimeError(f"missing required local environment variable {config.api_key_env}")
    return LiteLLMClient(config, api_key)
