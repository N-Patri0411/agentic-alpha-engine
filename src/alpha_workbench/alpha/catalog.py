"""Point-in-time feature catalog used to constrain generated factors."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeatureDefinition(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*$", min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    entity_scope: str = Field(default="cross_section", max_length=80)
    available_at: datetime | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)


class FeatureCatalog(BaseModel):
    features: list[FeatureDefinition] = Field(min_length=1, max_length=500)
    as_of_time: datetime | None = None

    @property
    def names(self) -> set[str]:
        return {f.name for f in self.features}

    def validate_point_in_time(self) -> None:
        if self.as_of_time is None:
            return
        future = [
            f.name for f in self.features if f.available_at and f.available_at > self.as_of_time
        ]
        if future:
            raise ValueError(f"features unavailable at as_of_time: {', '.join(future)}")
