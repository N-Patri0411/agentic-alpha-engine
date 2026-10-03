"""Immutable contracts for versioned, point-in-time feature frames."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from alpha_workbench.product.contracts import ContractBase

FeatureFamily = Literal[
    "graph_propagation",
    "neighbor_lag",
    "centrality_concentration",
    "statistical_lead_lag",
    "price_volume",
    "volatility",
    "fundamentals",
    "earnings_events",
    "language_drift",
    "macro_fx",
]
FeatureFrequency = Literal["daily", "weekly", "monthly", "quarterly", "event"]
FeatureValue = float | int | str | bool | None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("feature timestamps must include a timezone offset")
    return value


class FeatureDefinition(ContractBase):
    """Versioned schema and source contract for one deterministic feature."""

    feature_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=1)
    family: FeatureFamily
    description: str = Field(min_length=1)
    frequency: FeatureFrequency
    inputs: tuple[str, ...] = Field(min_length=1)
    output_type: Literal["float", "integer"] = "float"
    required_graph: bool = False


class FeatureSetVersion(ContractBase):
    """Immutable, pinned collection of feature definitions and source versions."""

    feature_set_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    feature_definition_refs: tuple[str, ...] = Field(min_length=1)
    dataset_versions: dict[str, str] = Field(default_factory=dict)
    graph_snapshot_id: str | None = Field(default=None, min_length=1)
    graph_snapshot_digest: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @model_validator(mode="after")
    def graph_pin_is_complete(self) -> FeatureSetVersion:
        if bool(self.graph_snapshot_id) != bool(self.graph_snapshot_digest):
            raise ValueError("graph snapshot ID and digest must be pinned together")
        if len(set(self.feature_definition_refs)) != len(self.feature_definition_refs):
            raise ValueError("feature definition references must be unique")
        return self


class FeatureInputObservation(ContractBase):
    """One source row with explicit value, observation, and availability clocks."""

    entity_id: str = Field(min_length=1)
    observed_at: datetime
    available_at: datetime
    values: dict[str, FeatureValue]

    @field_validator("observed_at", "available_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def availability_follows_observation(self) -> FeatureInputObservation:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self


class FeatureInputFrame(ContractBase):
    """Frozen dataset input presented to a feature family builder."""

    family: FeatureFamily
    frequency: FeatureFrequency
    dataset_version: str = Field(min_length=1)
    observations: tuple[FeatureInputObservation, ...] = ()


class FeatureObservation(ContractBase):
    """Computed scalar feature value with point-in-time provenance."""

    feature_id: str = Field(min_length=1)
    feature_name: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    observed_at: datetime
    available_at: datetime
    value: FeatureValue
    dataset_version: str | None = None
    graph_snapshot_id: str | None = Field(default=None, min_length=1)
    graph_snapshot_digest: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, value: FeatureValue) -> FeatureValue:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("feature values must be finite")
        return value

    @field_validator("observed_at", "available_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def availability_follows_observation(self) -> FeatureObservation:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        if bool(self.graph_snapshot_id) != bool(self.graph_snapshot_digest):
            raise ValueError("graph feature provenance must include snapshot ID and digest")
        return self

    @property
    def observation_id(self) -> str:
        """Stable logical identity; changed values under the same provenance cannot overwrite."""
        from alpha_workbench.product.canonical import canonical_json

        payload = self.model_dump(mode="json")
        payload.pop("value")
        return (
            "feature-observation-"
            + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:24]
        )


class FeatureReadiness(ContractBase):
    feature_id: str
    feature_name: str
    status: Literal["ready", "unavailable"]
    reason: str
    observation_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def ready_state_has_values(self) -> FeatureReadiness:
        if self.status == "ready" and self.observation_count == 0:
            raise ValueError("ready feature requires at least one observation")
        return self


class FeatureFrameManifest(ContractBase):
    """Immutable frame receipt, including computed values and full source pins."""

    manifest_id: str = Field(min_length=1)
    feature_set_id: str = Field(min_length=1)
    feature_set_version: int = Field(ge=1)
    feature_set_digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    feature_definition_digests: dict[str, str]
    as_of_time: datetime
    effective_time: datetime
    knowledge_time: datetime
    feature_observations: tuple[FeatureObservation, ...] = ()
    readiness: tuple[FeatureReadiness, ...] = ()
    dataset_versions: dict[str, str] = Field(default_factory=dict)
    graph_snapshot_id: str | None = Field(default=None, min_length=1)
    graph_snapshot_digest: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("as_of_time", "effective_time", "knowledge_time")
    @classmethod
    def cutoff_is_aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def provenance_is_consistent(self) -> FeatureFrameManifest:
        if self.effective_time > self.as_of_time:
            raise ValueError("effective_time cannot be after frame as_of_time")
        if self.knowledge_time > self.as_of_time:
            raise ValueError("knowledge_time cannot be after frame as_of_time")
        if bool(self.graph_snapshot_id) != bool(self.graph_snapshot_digest):
            raise ValueError("graph snapshot ID and digest must be pinned together")
        for item in self.feature_observations:
            if item.observed_at > self.as_of_time or item.available_at > self.as_of_time:
                raise ValueError("feature observation is after frame as_of_time")
        return self


class FeatureCatalogEntry(ContractBase):
    definition: FeatureDefinition
    readiness: FeatureReadiness
