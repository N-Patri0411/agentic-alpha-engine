"""Bounded evidence-to-graph batch assembly for a manual domain-map run."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .evidence import EvidenceObservation, TextEvidence
from .graph_registry import GraphSnapshot


class GraphBuildSelection(BaseModel):
    """Audit receipt for deterministic pre-model evidence selection."""

    selected_observation_ids: list[str] = Field(min_length=1)
    skipped_existing_pair_count: int = Field(ge=0)


def select_graph_build_observations(
    *,
    observations: list[EvidenceObservation],
    current_snapshot: GraphSnapshot,
    maximum_observations: int,
) -> tuple[list[EvidenceObservation], GraphBuildSelection]:
    """Select one official, pair-specific passage per unseen entity pair.

    A conservative limit keeps a manual Luna run predictable. Existing pairs are
    not re-proposed in a first domain-map build; later graph-maintenance runs
    will handle weight updates separately.
    """

    if maximum_observations < 1 or maximum_observations > 8:
        raise ValueError("maximum_observations must be between 1 and 8")
    existing_pairs = {
        frozenset((edge.upstream_entity_id, edge.downstream_entity_id))
        for edge in current_snapshot.edges
    }
    candidates = [
        observation
        for observation in observations
        if isinstance(observation.payload, TextEvidence)
        and observation.document.source_tier in {"primary", "official"}
        and len(observation.mentioned_entity_ids) == 2
    ]
    candidates.sort(
        key=lambda observation: (
            observation.document.source_url,
            str(observation.observation_id),
        )
    )
    selected: list[EvidenceObservation] = []
    selected_pairs: set[frozenset[str]] = set()
    skipped_existing = 0
    for observation in candidates:
        pair = frozenset(observation.mentioned_entity_ids)
        if pair in existing_pairs:
            skipped_existing += 1
            continue
        if pair in selected_pairs:
            continue
        selected.append(observation)
        selected_pairs.add(pair)
        if len(selected) == maximum_observations:
            break
    if not selected:
        raise ValueError("no unseen official pair-specific observations were available")
    return selected, GraphBuildSelection(
        selected_observation_ids=[str(observation.observation_id) for observation in selected],
        skipped_existing_pair_count=skipped_existing,
    )


def current_utc() -> datetime:
    """One testable time boundary for a manual graph-build invocation."""

    return datetime.now(UTC)
