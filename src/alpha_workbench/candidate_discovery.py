"""Bounded preparation for model-assisted candidate graph discovery."""

from __future__ import annotations

from itertools import combinations

from pydantic import BaseModel, Field

from .evidence import EvidenceObservation, TextEvidence
from .extraction import DocumentPassage


class CandidateDiscoverySelection(BaseModel):
    """Deterministic receipt for the passages allowed into a discovery run."""

    selected_observation_ids: list[str] = Field(min_length=1)
    skipped_non_text_count: int = Field(ge=0)
    selected_source_tiers: dict[str, int] = Field(default_factory=dict)

    @property
    def skipped_non_text_or_non_primary_count(self) -> int:
        """Backward-compatible alias for receipts written before source expansion."""

        return self.skipped_non_text_count


def select_candidate_discovery_observations(
    *, observations: list[EvidenceObservation], maximum_observations: int
) -> tuple[list[EvidenceObservation], CandidateDiscoverySelection]:
    """Select bounded text observations across all source tiers.

    Discovery summaries improve recall but retain weak provenance and require
    corroboration before promotion. Structured facts and market bars are not
    relationship text and remain excluded.
    """

    if maximum_observations < 1 or maximum_observations > 8:
        raise ValueError("maximum_observations must be between 1 and 8")
    candidates: list[EvidenceObservation] = []
    skipped = 0
    for observation in observations:
        is_eligible_text = isinstance(observation.payload, TextEvidence)
        if not is_eligible_text:
            skipped += 1
            continue
        candidates.append(observation)
    candidates.sort(
        key=lambda observation: (
            observation.document.available_at,
            str(observation.observation_id),
        )
    )
    # Greedily maximize novel mentioned-entity pairs. This avoids spending a
    # small model budget on repeated passages from one pair while preserving a
    # deterministic tie-break (source availability, URL, observation ID).
    selected: list[EvidenceObservation] = []
    remaining = list(candidates)
    covered_pairs: set[frozenset[str]] = set()
    covered_entities: set[str] = set()
    while remaining and len(selected) < maximum_observations:
        def score(item: EvidenceObservation) -> tuple[int, int]:
            pairs = {
                frozenset(pair)
                for pair in combinations(sorted(item.mentioned_entity_ids), 2)
            }
            new_pairs = len(pairs - covered_pairs)
            new_entities = len(set(item.mentioned_entity_ids) - covered_entities)
            # Candidates are pre-sorted earliest-first. Returning only
            # coverage metrics means max() retains that order on ties.
            return (new_pairs, new_entities)

        best = max(remaining, key=score)
        remaining.remove(best)
        selected.append(best)
        covered_pairs.update(
            frozenset(pair)
            for pair in combinations(sorted(best.mentioned_entity_ids), 2)
        )
        covered_entities.update(best.mentioned_entity_ids)
    if not selected:
        raise ValueError("no text observations were available")
    tiers: dict[str, int] = {}
    for observation in selected:
        tier = observation.document.source_tier
        tiers[tier] = tiers.get(tier, 0) + 1
    return selected, CandidateDiscoverySelection(
        selected_observation_ids=[str(observation.observation_id) for observation in selected],
        skipped_non_text_count=skipped,
        selected_source_tiers=tiers,
    )


def observation_to_passage(observation: EvidenceObservation) -> DocumentPassage:
    """Preserve the original source span while adapting shared evidence to the extractor."""

    if not isinstance(observation.payload, TextEvidence):
        raise TypeError("candidate discovery requires text evidence")
    payload = observation.payload
    return DocumentPassage(
        snapshot_sha256=observation.document.content_sha256,
        source_url=observation.document.source_url,
        start_offset=payload.character_start,
        end_offset=payload.character_end,
        text=payload.text,
        matching_keywords=["candidate_discovery"],
        source_tier=observation.document.source_tier,
        source_kind=observation.document.source_kind,
        source_adapter=observation.document.source_adapter,
        source_title=observation.document.title,
        observation_id=str(observation.observation_id),
        evidence_basis=(
            "discovery_summary"
            if observation.document.source_tier == "discovery"
            else "full_text"
        ),
    )
