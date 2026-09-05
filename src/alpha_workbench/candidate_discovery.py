"""Bounded preparation for model-assisted candidate graph discovery."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .evidence import EvidenceObservation, TextEvidence
from .extraction import DocumentPassage


class CandidateDiscoverySelection(BaseModel):
    """Deterministic receipt for the passages allowed into a discovery run."""

    selected_observation_ids: list[str] = Field(min_length=1)
    skipped_non_text_or_non_primary_count: int = Field(ge=0)


def select_candidate_discovery_observations(
    *, observations: list[EvidenceObservation], maximum_observations: int
) -> tuple[list[EvidenceObservation], CandidateDiscoverySelection]:
    """Select a small, stable set of official text observations.

    Discovery results are useful locators but are not evidence by themselves.
    This function therefore accepts only primary or official full-text evidence,
    leaving the model with an auditable, bounded input set.
    """

    if maximum_observations < 1 or maximum_observations > 8:
        raise ValueError("maximum_observations must be between 1 and 8")
    candidates: list[EvidenceObservation] = []
    skipped = 0
    for observation in observations:
        is_eligible_text = isinstance(observation.payload, TextEvidence)
        is_primary_source = observation.document.source_tier in {
            "primary",
            "official",
        }
        if not is_eligible_text or not is_primary_source:
            skipped += 1
            continue
        candidates.append(observation)
    candidates.sort(
        key=lambda observation: (
            observation.document.available_at,
            str(observation.observation_id),
        )
    )
    selected = candidates[:maximum_observations]
    if not selected:
        raise ValueError("no primary or official text observations were available")
    return selected, CandidateDiscoverySelection(
        selected_observation_ids=[str(observation.observation_id) for observation in selected],
        skipped_non_text_or_non_primary_count=skipped,
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
    )
