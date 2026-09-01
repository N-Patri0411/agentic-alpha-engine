"""Stable envelopes exchanged by agents without direct agent-to-agent imports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ..agents.contracts import AgentName, ArtifactRef

MessageType = Literal["command", "result", "review_request", "review_decision", "error"]


class A2AMessage(BaseModel):
    schema_version: str = "1"
    message_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(min_length=1)
    parent_message_id: UUID | None = None
    run_id: str = Field(min_length=1)
    sender: AgentName
    recipient: AgentName
    message_type: MessageType
    created_at: datetime
    idempotency_key: str = Field(min_length=1)
    policy_context: dict[str, str | int | float | bool] = Field(default_factory=dict)
    artifact_references: list[ArtifactRef] = Field(default_factory=list)
    typed_payload: dict[str, object] = Field(default_factory=dict)
