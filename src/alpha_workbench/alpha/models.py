"""Serializable outputs of the alpha generator."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .dsl import canonicalize_expression, parse_expression


class CandidateProvenance(BaseModel):
    generated_by: str = Field(min_length=1)
    feature_names: list[str] = Field(min_length=1)
    source_artifact_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    request_fingerprint: str = Field(min_length=8)


class FeatureReference(BaseModel):
    """Typed, version-pinned feature consumed by an immutable signal."""

    name: str
    value_type: Literal["numeric"] = "numeric"
    frequency: Literal["daily", "weekly", "monthly", "quarterly"]
    feature_version_id: str | None = None
    dataset_version_id: str | None = None
    graph_version_id: str | None = None
    source_artifact_ids: tuple[str, ...] = ()


class SignalSpec(BaseModel):
    """Immutable executable signal definition; no model-generated code is stored."""

    model_config = {"frozen": True, "extra": "forbid"}

    schema_version: Literal["1"] = "1"
    expression: str = Field(min_length=1, max_length=300)
    canonical_expression: str = Field(min_length=1, max_length=300)
    frequency: Literal["daily", "weekly", "monthly"]
    feature_frequency_policy: Literal["strict", "quarterly_release_to_monthly"] = "strict"
    feature_refs: tuple[FeatureReference, ...] = Field(min_length=1)
    as_of_time: datetime | None = None
    rationale: str = Field(min_length=1, max_length=1000)
    provenance: CandidateProvenance | None = None
    graph_version_id: str | None = None
    portfolio_config: dict[str, Any] = Field(default_factory=dict)
    risk_config: dict[str, Any] = Field(default_factory=dict)
    validation_config: dict[str, Any] = Field(default_factory=dict)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(reference.name for reference in self.feature_refs)

    @property
    def dataset_version_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    reference.dataset_version_id
                    for reference in self.feature_refs
                    if reference.dataset_version_id
                }
            )
        )

    def to_strategy_spec(
        self, *, strategy_id: str, workspace_id: str, universe_id: str, name: str
    ) -> Any:
        """Adapt into the durable product strategy contract without duplicating it."""
        from ..product.contracts import StrategySpec

        return StrategySpec(
            strategy_id=strategy_id,
            workspace_id=workspace_id,
            universe_id=universe_id,
            name=name,
            cadence=self.frequency,
            signal_expression=self.canonical_expression,
            feature_names=self.feature_names,
            feature_version_ids=tuple(
                sorted(
                    {
                        reference.feature_version_id
                        for reference in self.feature_refs
                        if reference.feature_version_id
                    }
                )
            ),
            portfolio_config=self.portfolio_config,
            risk_config=self.risk_config,
            validation_config={
                **self.validation_config,
                "feature_frequency_policy": self.feature_frequency_policy,
            },
            dataset_version_ids=self.dataset_version_ids,
            graph_version_id=self.graph_version_id,
        )


class ExperimentTrialLedger(BaseModel):
    """Append-only style experiment accounting contract shared by generation/evaluation."""

    model_config = {"frozen": True, "extra": "forbid"}

    experiment_id: str = Field(min_length=1)
    trial_count: int = Field(default=0, ge=0)
    trial_limit: int = Field(default=100, ge=1, le=100_000)
    canonical_formulas: tuple[str, ...] = ()

    def record(self, canonical_formula: str) -> ExperimentTrialLedger:
        if canonical_formula in self.canonical_formulas:
            return self
        if self.trial_count >= self.trial_limit:
            raise ValueError("experiment trial limit exceeded")
        return self.model_copy(
            update={
                "trial_count": self.trial_count + 1,
                "canonical_formulas": (*self.canonical_formulas, canonical_formula),
            }
        )


class AlphaCandidate(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=1000)
    provenance: CandidateProvenance
    signal: SignalSpec | None = None

    def validate_expression(self, feature_names: set[str]) -> None:
        parse_expression(self.expression, feature_names)

    @property
    def canonical_expression(self) -> str:
        names = self.signal.feature_names if self.signal else self.provenance.feature_names
        return canonicalize_expression(self.expression, set(names))


class AlphaGenerationResult(BaseModel):
    candidates: list[AlphaCandidate] = Field(max_length=50)
    rejected: list[str] = Field(default_factory=list, max_length=100)
    as_of_time: datetime | None = None
    experiment_id: str | None = None
    trial_count: int = Field(default=0, ge=0)
    trial_limit: int | None = Field(default=None, ge=1)
