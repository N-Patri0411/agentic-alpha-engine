"""Versioned, transport-neutral agent-to-agent communication."""

from .bus import DuckDBMessageBus
from .contracts import A2AMessage

__all__ = ["A2AMessage", "DuckDBMessageBus"]
