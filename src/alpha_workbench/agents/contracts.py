"""Typed, serializable contracts shared across the planned agent system."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "orchestrator",
    "extraction",
    "graph_adjudicator",
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
        "graph_adjudicator",
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
    trigger: Literal["decay", "stale_data", "crowding", "replacement_needed"]
    measured_at: datetime
    detail: str


class SignalMetricObservation(BaseModel):
    """One already-realised, point-in-time metric used by the Monitor.

    These are observations produced by the deterministic research/evaluation
    layer.  The Monitor never invents missing metrics or treats a future
    observation as if it were known at the requested research cutoff.
    """

    as_of_time: datetime
    available_at: datetime
    rank_ic: float | None = None
    net_return: float | None = None
    correlation_to_library: float | None = None


class MonitorPolicy(BaseModel):
    """Explicit deterministic thresholds for signal-health decisions."""

    rolling_window: int = Field(default=20, ge=3, le=2520)
    min_observations: int = Field(default=20, ge=1, le=2520)
    stale_after_days: float = Field(default=7.0, gt=0, le=3650)
    decay_ic_delta: float = Field(default=0.10, gt=0, le=2)
    decay_return_delta: float = Field(default=0.01, gt=0, le=10)
    negative_ic_threshold: float = Field(default=-0.05, ge=-1, le=1)
    negative_return_threshold: float = Field(default=0.0, ge=-10, le=10)
    crowding_correlation_threshold: float = Field(default=0.80, ge=-1, le=1)


class SignalHealthSnapshot(BaseModel):
    """The Monitor's measured health, without a retirement decision."""

    hypothesis_id: str
    measured_at: datetime
    observation_count: int = Field(ge=0)
    rolling_rank_ic: float | None = None
    rolling_net_return: float | None = None
    correlation_to_library: float | None = None
    quality_drift: float | None = None
    decay_score: float | None = Field(default=None, ge=0, le=1)
    freshness_age_days: float | None = Field(default=None, ge=0)
    status: Literal["active", "watch"]


class MonitorEvaluationRequest(BaseModel):
    """Input envelope for one deterministic Monitor evaluation."""

    hypothesis_id: str = Field(min_length=1, max_length=200)
    as_of_time: datetime
    measured_at: datetime
    observations: list[SignalMetricObservation] = Field(min_length=1)
    latest_input_available_at: datetime | None = None
    policy: MonitorPolicy = Field(default_factory=MonitorPolicy)


class GatekeeperReviewEvent(BaseModel):
    """Typed handoff from Monitor to Gatekeeper.

    This event requests a review; it does not retire a signal or modify the
    signal library.  Gatekeeper remains the only component allowed to make
    that policy decision.
    """

    event_id: str = Field(min_length=8)
    source_agent: Literal["monitor"] = "monitor"
    hypothesis_id: str = Field(min_length=1)
    trigger: Literal["decay", "stale_data", "crowding", "replacement_needed"]
    as_of_time: datetime
    measured_at: datetime
    reasons: list[str] = Field(min_length=1)
    health: SignalHealthSnapshot


class MonitorEvaluationResult(BaseModel):
    """Complete Monitor output, including an optional Gatekeeper review event."""

    hypothesis_id: str
    as_of_time: datetime
    measured_at: datetime
    status: Literal["healthy", "watch", "needs_review", "insufficient_data"]
    health: SignalHealthSnapshot
    reasons: list[str] = Field(default_factory=list)
    review_event: GatekeeperReviewEvent | None = None
