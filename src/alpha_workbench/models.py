"""Stable, serializable contracts shared by research modules."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DatasetSnapshot(BaseModel):
    """A reproducible record of a source dataset at retrieval time."""

    source: str
    content_sha256: str = Field(min_length=64, max_length=64)
    retrieved_at: datetime
    usage_note: str
    schema_version: str = "1"


class FeatureSpec(BaseModel):
    """Documents inputs and timing guarantees for a derived feature."""

    name: str
    input_snapshots: list[str] = Field(min_length=1)
    transformation: str
    availability_rule: str
    output_schema: dict[str, str]


class Hypothesis(BaseModel):
    """A human- or model-authored research statement, never a trade instruction."""

    id: str
    rationale: str
    dsl_expression: str
    author: str
    status: Literal["draft", "testing", "accepted", "rejected"] = "draft"


class ResearchRun(BaseModel):
    """Immutable context for a replayable research execution."""

    id: str
    as_of_time: datetime
    code_version: str
    dataset_snapshot_ids: list[str] = Field(min_length=1)
    started_at: datetime
    configuration: dict[str, str | int | float | bool]


class BacktestReport(BaseModel):
    """Initial paper-research report; metrics are diagnostics, not claims of alpha."""

    as_of_time: datetime
    periods: int
    mean_rank_ic: float | None
    gross_return: float
    net_return: float
    annualized_sharpe: float | None
    max_drawdown: float
    average_turnover: float
    transaction_cost_bps: float
    trial_count: int = Field(ge=1)
    limitations: list[str]


class SignalHealth(BaseModel):
    """Stores a signal's observed quality and retirement state."""

    hypothesis_id: str
    measured_at: datetime
    rolling_rank_ic: float | None
    correlation_to_library: float | None
    status: Literal["active", "watch", "retired"]


class ScenarioPathEdge(BaseModel):
    """One explainable relationship in a propagated supply-chain path."""

    source: str
    target: str
    relationship: str
    source_url: str
    edge_weight: float = Field(ge=0, le=1)
    substitutability: float = Field(ge=0, le=1)


class ScenarioImpact(BaseModel):
    """A propagated scenario impact for an entity."""

    entity: str
    severity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    path: list[ScenarioPathEdge]


class ScenarioResult(BaseModel):
    """A source-backed, effective-dated scenario calculation."""

    shock_entity: str
    shock_severity: float = Field(ge=0, le=1)
    as_of_time: datetime
    impacts: list[ScenarioImpact]
    limitations: list[str]
