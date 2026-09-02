"""Versioned payloads for the first Extraction-to-Graph agent hand-off."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..evidence import EvidenceObservation
from ..extraction import EdgeProposal, EvidenceValidationReport


class ExtractionCommandPayload(BaseModel):
    observations: list[EvidenceObservation] = Field(min_length=1)
    known_entities: set[str] = Field(min_length=2)


class GraphReviewRequestPayload(BaseModel):
    """Only Extraction proposals that passed deterministic validation may enter."""

    as_of_time: datetime
    observations: list[EvidenceObservation] = Field(min_length=1)
    validated_proposals: list[EdgeProposal] = Field(min_length=1)
    validation_reports: list[EvidenceValidationReport] = Field(min_length=1)
