"""Opt-in boundary for explicitly registered, hash-pinned trusted operators.

This registry does not parse, import, compile, or execute model-provided Python.
An application may register a locally installed callable by name after pinning
the exact normalized source hash. The registry is disabled by default.
"""

from __future__ import annotations

import hashlib
import inspect
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ExtensionPolicyError(ValueError):
    """Raised when an extension is not allowed by the local policy."""


@dataclass(frozen=True)
class RegisteredExtension:
    name: str
    source_sha256: str
    function: Callable[..., Any]


class AdvancedPythonExtensionRegistry:
    """Registry for host-selected callables; never accepts model code or imports."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._items: dict[str, RegisteredExtension] = {}

    @staticmethod
    def source_hash(function: Callable[..., Any]) -> str:
        try:
            source = textwrap.dedent(inspect.getsource(function)).strip()
        except (OSError, TypeError) as error:
            raise ExtensionPolicyError("extension source must be locally inspectable") from error
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def register(
        self,
        name: str,
        function: Callable[..., Any],
        *,
        pinned_sha256: str,
    ) -> RegisteredExtension:
        if not self.enabled:
            raise ExtensionPolicyError("advanced Python extensions are disabled")
        if not name.isidentifier() or name.startswith("_"):
            raise ExtensionPolicyError("extension name must be a public identifier")
        actual = self.source_hash(function)
        if actual != pinned_sha256.lower():
            raise ExtensionPolicyError("extension source hash does not match the pin")
        item = RegisteredExtension(name=name, source_sha256=actual, function=function)
        self._items[name] = item
        return item

    def resolve(self, name: str, *, pinned_sha256: str) -> RegisteredExtension:
        if not self.enabled:
            raise ExtensionPolicyError("advanced Python extensions are disabled")
        item = self._items.get(name)
        if item is None or item.source_sha256 != pinned_sha256.lower():
            raise ExtensionPolicyError("extension is not explicitly registered and pinned")
        if self.source_hash(item.function) != item.source_sha256:
            raise ExtensionPolicyError("registered extension changed after pinning")
        return item
