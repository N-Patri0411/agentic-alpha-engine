"""Point-in-time feature catalog used to constrain generated factors."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GeneratorFeatureRef(BaseModel):
    """Typed feature input accepted by the alpha-generator boundary."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    entity_scope: str = Field(default="cross_section", max_length=80)
    frequency: Literal["daily", "weekly", "monthly", "quarterly"] = "daily"
    value_type: Literal["numeric"] = "numeric"
    feature_version_id: str | None = None
    dataset_version_id: str | None = None
    graph_version_id: str | None = None
    supported_axes: tuple[Literal["cross_section", "time_series"], ...] = Field(
        default=(
        "cross_section", "time_series"
        ), min_length=1
    )
    available_at: datetime | None = None
    available: bool = True
    source_artifact_ids: list[str] = Field(default_factory=list)


class FeatureCatalog(BaseModel):
    features: list[GeneratorFeatureRef] = Field(min_length=1, max_length=500)
    as_of_time: datetime | None = None
    frequency: Literal["daily", "weekly", "monthly"] = "daily"
    feature_frequency_policy: Literal["strict", "quarterly_release_to_monthly"] = "strict"
    graph_version_id: str | None = None

    @model_validator(mode="after")
    def unique_features(self) -> FeatureCatalog:
        names = [feature.name for feature in self.features]
        if len(names) != len(set(names)):
            raise ValueError("feature catalog contains duplicate names")
        return self

    @property
    def names(self) -> set[str]:
        return {f.name for f in self.features}

    def validate_point_in_time(self) -> None:
        unavailable = [f.name for f in self.features if not f.available]
        if self.as_of_time is not None:
            if self.as_of_time.tzinfo is None or self.as_of_time.utcoffset() is None:
                raise ValueError("as_of_time must be timezone-aware")
            for feature in self.features:
                if feature.available_at is not None:
                    if (
                        feature.available_at.tzinfo is None
                        or feature.available_at.utcoffset() is None
                    ):
                        raise ValueError(
                            f"feature {feature.name!r} available_at must be timezone-aware"
                        )
                    if feature.available_at > self.as_of_time:
                        unavailable.append(feature.name)
        if unavailable:
            names = ", ".join(sorted(set(unavailable)))
            raise ValueError(f"features unavailable at as_of_time: {names}")

    def validate_frequency(
        self, requested: str | None = None, policy: str | None = None
    ) -> str:
        frequency = requested or self.frequency
        selected_policy = policy or self.feature_frequency_policy
        mismatched = [
            f.name
            for f in self.features
            if f.frequency != frequency
            and not (
                frequency == "monthly"
                and f.frequency == "quarterly"
                and selected_policy == "quarterly_release_to_monthly"
                and f.available_at is not None
                and self.as_of_time is not None
            )
        ]
        if mismatched:
            raise ValueError(
                f"feature frequency mismatch for {frequency}: {', '.join(sorted(mismatched))}"
            )
        return frequency


# Source-compatibility alias. New API and integration code should use the
# explicitly scoped name so this doesn't shadow alpha_workbench.features.
FeatureDefinition = GeneratorFeatureRef
