"""Least-privilege tool registration separate from agent behavior."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

ToolCallable = Callable[[dict[str, Any]], dict[str, Any]]


class CapabilityManifest:
    def __init__(self, agent_tools: dict[str, set[str]]) -> None:
        self._agent_tools = agent_tools

    @classmethod
    def from_yaml(cls, path: Path) -> CapabilityManifest:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("agents"), dict):
            raise ValueError("capability manifest must contain an agents mapping")
        agent_tools: dict[str, set[str]] = {}
        for agent, tools in raw["agents"].items():
            if not isinstance(agent, str) or not isinstance(tools, list) or not all(
                isinstance(tool, str) for tool in tools
            ):
                raise ValueError("each agent capability list must contain tool names")
            agent_tools[agent] = set(tools)
        return cls(agent_tools)

    def tools_for(self, agent: str) -> set[str]:
        return set(self._agent_tools.get(agent, set()))


class ToolRegistry:
    """One catalog; agents receive only manifest-authorized tool callables."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCallable] = {}

    def register(self, name: str, tool: ToolCallable) -> None:
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        self._tools[name] = tool

    def resolve(self, agent: str, manifest: CapabilityManifest) -> dict[str, ToolCallable]:
        granted = manifest.tools_for(agent)
        missing = granted.difference(self._tools)
        if missing:
            raise ValueError(f"unregistered tools in {agent!r} manifest: {sorted(missing)}")
        return {name: self._tools[name] for name in sorted(granted)}
