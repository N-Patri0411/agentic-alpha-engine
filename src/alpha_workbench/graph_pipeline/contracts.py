"""Typed requests and deterministic decisions for autonomous graph maintenance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alpha_workbench.evidence import EvidenceObservation
from alpha_workbench.extraction import EdgeProposal, EvidenceValidationReport
from alpha_workbench.product import UniverseSpec


class EvidenceAssessment(BaseModel):
    """Semantic classification attached to immutable evidence.

    An adjudicator may classify a statement as support, contradiction, or
    retirement. It cannot set graph weights or override deterministic policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1)
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1)
    stance: Literal["support", "contradict", "retire"]


class GraphPipelineRequest(BaseModel):
    """All inputs required for one repeatable bootstrap or maintenance run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    universe: UniverseSpec
    as_of_time: datetime
    knowledge_time: datetime
    observations: tuple[EvidenceObservation, ...] = ()
    validated_proposals: tuple[EdgeProposal, ...] = ()
    validation_reports: tuple[EvidenceValidationReport, ...] = ()
    assessments: tuple[EvidenceAssessment, ...] = ()
    aliases: dict[str, str] = Field(default_factory=dict)
    trigger: Literal["bootstrap", "nightly", "event"] = "bootstrap"
    request_id: str | None = None

    @field_validator("as_of_time", "knowledge_time")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("graph pipeline timestamps must be timezone-aware")
        return value


class EdgeEligibility(BaseModel):
    """Auditable deterministic policy outcome for one logical edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_node_id: str
    target_node_id: str
    relationship_id: str
    status: Literal["eligible", "ineligible", "review_required"]
    confidence: float = Field(ge=0, le=1)
    independent_sources: int = Field(ge=0)
    support_count: int = Field(ge=0)
    contradiction_count: int = Field(ge=0)
    reason: str


class GraphPipelineReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    published: bool
    idempotent_replay: bool = False
    trigger: Literal["bootstrap", "nightly", "event"]
    affected_edge_ids: tuple[str, ...] = ()
    decisions: tuple[EdgeEligibility, ...] = ()
    excluded_observation_ids: tuple[str, ...] = ()
