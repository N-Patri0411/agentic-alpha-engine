"""Catalog and readiness projections for feature builders and stored frames."""

from __future__ import annotations

from .contracts import (
    FeatureCatalogEntry,
    FeatureDefinition,
    FeatureFrameManifest,
    FeatureReadiness,
)


def feature_catalog(
    definitions: tuple[FeatureDefinition, ...],
    manifest: FeatureFrameManifest | None = None,
) -> tuple[FeatureCatalogEntry, ...]:
    """Return each defined feature with computed readiness or an honest unavailable state."""
    readiness_by_id = {item.feature_id: item for item in (manifest.readiness if manifest else ())}
    output = []
    for definition in definitions:
        readiness = readiness_by_id.get(definition.feature_id)
        if readiness is None:
            readiness = FeatureReadiness(
                feature_id=definition.feature_id,
                feature_name=definition.name,
                status="unavailable",
                reason="feature has not been built for this frame",
                created_at=definition.created_at,
            )
        output.append(FeatureCatalogEntry(definition=definition, readiness=readiness))
    return tuple(output)


def feature_readiness(manifest: FeatureFrameManifest) -> tuple[FeatureReadiness, ...]:
    """Expose the manifest's per-feature ready/unavailable decisions."""
    return manifest.readiness
