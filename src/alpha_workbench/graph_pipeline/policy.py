"""Deterministic evidence thresholds; semantic models never choose eligibility."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from alpha_workbench.evidence import EvidenceObservation

from .contracts import EdgeEligibility, EvidenceAssessment

SOURCE_RELIABILITY = {
    "primary": 0.90,
    "official": 0.75,
    "discovery": 0.35,
    "market_data": 0.50,
}
MIN_INDEPENDENT_SOURCES = 2
MIN_CONFIDENCE = 0.50
MAX_CONTRADICTION_SHARE = 0.30
EVIDENCE_HALF_LIFE_DAYS = 180.0
RETIRE_AFTER_HALF_LIVES = 4.0


def source_identity(observation: EvidenceObservation) -> str:
    """Group distinct URLs from one host/adapter as one source for corroboration."""
    from urllib.parse import urlsplit

    host = (urlsplit(observation.document.source_url).hostname or "").lower()
    return host or observation.document.source_adapter.casefold()


def evidence_quality(observation: EvidenceObservation, at: datetime) -> float:
    age_days = max(0.0, (at - observation.document.available_at).total_seconds() / 86_400)
    half_life = 30.0 if observation.document.source_tier == "discovery" else EVIDENCE_HALF_LIFE_DAYS
    freshness = math.exp(-math.log(2) * age_days / half_life)
    return SOURCE_RELIABILITY[observation.document.source_tier] * freshness


def assess_edge(
    *,
    source_node_id: str,
    target_node_id: str,
    relationship_id: str,
    observations: Sequence[EvidenceObservation],
    assessments: Sequence[EvidenceAssessment],
    at: datetime,
) -> EdgeEligibility:
    by_id = {str(item.observation_id): item for item in observations}
    stance_by_id = {item.observation_id: item.stance for item in assessments}
    supporters: dict[str, float] = {}
    for observation_id, observation in by_id.items():
        stance = stance_by_id.get(observation_id, "support")
        identity = source_identity(observation)
        quality = evidence_quality(observation, at)
        if stance == "contradict":
            continue
        elif stance in {"support", "retire"}:
            supporters[identity] = max(supporters.get(identity, 0.0), quality)
    support_count = sum(
        1 for item in by_id if stance_by_id.get(item, "support") in {"support", "retire"}
    )
    contradiction_count = sum(1 for item in by_id if stance_by_id.get(item) == "contradict")
    # One contribution per independent source; corroboration saturates at 1.
    support_confidence = 1.0 - math.prod(1.0 - value for value in supporters.values())
    total = support_count + contradiction_count
    contradiction_share = contradiction_count / total if total else 0.0
    confidence = support_confidence * (1.0 - contradiction_share)
    retire_sources = {
        source_identity(by_id[item]) for item in by_id if stance_by_id.get(item) == "retire"
    }
    status: Literal["eligible", "ineligible", "review_required"]
    if len(retire_sources) >= MIN_INDEPENDENT_SOURCES and contradiction_count == 0:
        status, reason = "ineligible", "independent evidence supports retirement"
    elif len(supporters) >= MIN_INDEPENDENT_SOURCES and confidence >= MIN_CONFIDENCE:
        if contradiction_share <= MAX_CONTRADICTION_SHARE:
            status, reason = "eligible", "corroborated evidence passed deterministic thresholds"
        else:
            status, reason = "review_required", "conflicting evidence exceeds policy limit"
    elif contradiction_count and (not supporters or contradiction_share > MAX_CONTRADICTION_SHARE):
        status, reason = "review_required", "evidence is conflicting or lacks corroborated support"
    else:
        status, reason = "ineligible", "insufficient independent corroboration"
    return EdgeEligibility(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relationship_id=relationship_id,
        status=status,
        confidence=round(max(0.0, min(1.0, confidence)), 6),
        independent_sources=len(supporters),
        support_count=support_count,
        contradiction_count=contradiction_count,
        reason=reason,
    )
