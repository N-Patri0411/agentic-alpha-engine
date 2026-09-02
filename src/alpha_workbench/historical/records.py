"""Immutable, source-backed records for historical scenario research."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from ..models import ScenarioResult


class ScenarioEvidence(BaseModel):
    observation_id: UUID
    source_url: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoricalEvent(BaseModel):
    """An event known at a precise time; not a hindsight narrative."""

    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    event_kind: Literal[
        "capacity_disruption",
        "geographic_or_regulatory",
        "demand_shock",
        "competitive_change",
        "other",
    ]
    description: str = Field(min_length=1)
    shock_entity_id: str = Field(min_length=1)
    shock_severity: float = Field(ge=0, le=1)
    observed_at: datetime
    available_at: datetime
    evidence: list[ScenarioEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_was_available_after_observation(self) -> HistoricalEvent:
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("event timestamps must include a timezone")
        if self.available_at < self.observed_at:
            raise ValueError("event available_at cannot precede observed_at")
        return self


class HistoricalScenarioRun(BaseModel):
    """Write-once receipt for a replay against one historical graph snapshot."""

    schema_version: Literal["1"] = "1"
    scenario_run_id: UUID = Field(default_factory=uuid4)
    event: HistoricalEvent
    graph_snapshot_id: str = Field(min_length=1)
    graph_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of_time: datetime
    created_at: datetime
    result: ScenarioResult

    @model_validator(mode="after")
    def replay_is_time_consistent(self) -> HistoricalScenarioRun:
        if self.as_of_time.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("scenario-run timestamps must include a timezone")
        if self.event.available_at > self.as_of_time:
            raise ValueError("event evidence was unavailable at the scenario as-of time")
        if self.result.as_of_time != self.as_of_time:
            raise ValueError("scenario result must use the recorded as-of time")
        if self.result.shock_entity != self.event.shock_entity_id:
            raise ValueError("scenario result shock entity must match the event")
        if self.result.shock_severity != self.event.shock_severity:
            raise ValueError("scenario result shock severity must match the event")
        return self
