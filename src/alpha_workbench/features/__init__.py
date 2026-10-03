"""Versioned deterministic feature platform."""

from .builders import build_feature_frame, default_feature_catalog
from .contracts import (
    FeatureCatalogEntry,
    FeatureDefinition,
    FeatureFamily,
    FeatureFrameManifest,
    FeatureFrequency,
    FeatureInputFrame,
    FeatureInputObservation,
    FeatureObservation,
    FeatureReadiness,
    FeatureSetVersion,
)
from .repository import (
    FeatureRepository,
    ImmutableFeatureRecordError,
    InMemoryFeatureRepository,
    PostgresFeatureRepository,
)
from .service import feature_catalog, feature_readiness
from .workspace_bindings import (
    InMemoryWorkspaceFeatureBindingRepository,
    PostgresWorkspaceFeatureBindingRepository,
    WorkspaceFeatureBinding,
    WorkspaceFeatureBindingRepository,
)

__all__ = [
    "FeatureCatalogEntry",
    "FeatureDefinition",
    "FeatureFamily",
    "FeatureFrameManifest",
    "FeatureFrequency",
    "FeatureInputFrame",
    "FeatureInputObservation",
    "FeatureObservation",
    "FeatureReadiness",
    "FeatureRepository",
    "FeatureSetVersion",
    "ImmutableFeatureRecordError",
    "InMemoryFeatureRepository",
    "PostgresFeatureRepository",
    "build_feature_frame",
    "default_feature_catalog",
    "feature_catalog",
    "feature_readiness",
    "InMemoryWorkspaceFeatureBindingRepository",
    "PostgresWorkspaceFeatureBindingRepository",
    "WorkspaceFeatureBinding",
    "WorkspaceFeatureBindingRepository",
]
