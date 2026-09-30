"""Serializable outputs of the alpha generator."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .dsl import parse_expression


class CandidateProvenance(BaseModel):
    generated_by: str = Field(min_length=1)
    feature_names: list[str] = Field(min_length=1)
    source_artifact_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    request_fingerprint: str = Field(min_length=8)


class AlphaCandidate(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=1000)
    provenance: CandidateProvenance

    def validate_expression(self, feature_names: set[str]) -> None:
        parse_expression(self.expression, feature_names)


class AlphaGenerationResult(BaseModel):
    candidates: list[AlphaCandidate] = Field(max_length=50)
    rejected: list[str] = Field(default_factory=list, max_length=100)
    as_of_time: datetime | None = None
