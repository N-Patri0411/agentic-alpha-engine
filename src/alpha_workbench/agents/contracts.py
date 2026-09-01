"""Typed, serializable contracts shared across the planned agent system."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "orchestrator",
    "extraction",
    "alpha_generator",
    "backtester",
    "gatekeeper",
    "portfolio_optimiser",
    "monitor",
    "research",
]
RunStatus = Literal["pending", "running", "paused", "completed", "failed", "loop_detected"]


class ArtifactRef(BaseModel):
    id: str
    kind: str
    sha256: str | None = None


class RunBudget(BaseModel):
    max_steps: int = Field(default=12, ge=1, le=100)
    max_retries_per_action: int = Field(default=2, ge=0, le=10)
    max_llm_calls: int = Field(default=20, ge=0, le=1000)
    max_runtime_seconds: int = Field(default=900, ge=1, le=86_400)


class AgentRequest(BaseModel):
    run_id: str
    agent: AgentName
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class AgentResult(BaseModel):
    run_id: str
    agent: AgentName
    status: Literal["completed", "paused", "failed"]
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    message: str
    latency_ms: int = Field(ge=0)


class NextAction(BaseModel):
    action: Literal[
        "extraction",
        "alpha_generator",
        "backtester",
        "gatekeeper",
        "portfolio_optimiser",
        "monitor",
        "research",
        "complete",
        "pause_for_review",
    ]
    reason: str = Field(min_length=1, max_length=500)


class RunEvent(BaseModel):
    at: datetime
    action: str
    input_hash: str
    idempotency_key: str
    detail: str


class AgentRun(BaseModel):
    id: str
    status: RunStatus = "pending"
    created_at: datetime
    budget: RunBudget = Field(default_factory=RunBudget)
    steps: int = 0
    llm_calls: int = 0
    events: list[RunEvent] = Field(default_factory=list)


class FeatureObservation(BaseModel):
    feature_name: str
    entity_id: str
    as_of_time: datetime
    available_at: datetime
    value: float
    source_artifacts: list[ArtifactRef] = Field(min_length=1)


class FormulaCandidate(BaseModel):
    id: str
    expression: str
    rationale: str
    feature_names: list[str] = Field(min_length=1)


class GateDecision(BaseModel):
    candidate_id: str
    decision: Literal["accepted", "rejected", "needs_review"]
    reasons: list[str] = Field(min_length=1)


class MonitorTrigger(BaseModel):
    hypothesis_id: str
    trigger: Literal["decay", "stale_data", "replacement_needed"]
    measured_at: datetime
    detail: str
