"""Versioned, transport-neutral agent-to-agent communication."""

from .bus import DuckDBMessageBus
from .contracts import A2AMessage
from .payloads import ExtractionCommandPayload, GraphReviewRequestPayload

__all__ = [
    "A2AMessage",
    "DuckDBMessageBus",
    "ExtractionCommandPayload",
    "GraphReviewRequestPayload",
]
