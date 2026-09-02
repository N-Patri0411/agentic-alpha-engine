"""Typed draft graph relationships and deterministic evidence validation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from ..llm.models import LLMClient
from .sections import DocumentPassage

RelationshipType = Literal[
    "manufacturing_dependency",
    "equipment_dependency",
    "packaging_dependency",
    "customer_concentration",
    "competitive_substitution",
    "ip_or_license",
    "geographic_or_regulatory",
]
ValidationVerdict = Literal["pass", "needs_review", "fail"]


class EdgeProposal(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    relationship_type: RelationshipType
    evidence_quote: str = Field(min_length=10)
    passage: DocumentPassage
    rationale: str = Field(min_length=1)
    suggested_confidence: float = Field(ge=0, le=1)
    status: Literal["draft", "validated", "rejected"] = "draft"


class NoEdgeProposal(BaseModel):
    status: Literal["no_proposal"] = "no_proposal"
    reason: str = Field(min_length=1)
    passage: DocumentPassage


class EvidenceValidationReport(BaseModel):
    proposal_id: UUID
    verdict: ValidationVerdict
    reasons: list[str] = Field(min_length=1)


class EvidenceProposalExtractor:
    """LLM wrapper that can create drafts but cannot write an active graph edge."""

    def __init__(self, llm: LLMClient, known_entities: set[str]) -> None:
        self._llm = llm
        self._known_entities = known_entities

    def extract(
        self, passage: DocumentPassage, *, issuer_entity_id: str | None = None
    ) -> EdgeProposal | NoEdgeProposal:
        raw = self._llm.complete_json(
            system=(
                "Use only the supplied passage as evidence. Never invent an entity, quote, "
                "or relationship. If the passage does not explicitly support one relationship "
                "between two known entities, return exactly a no-proposal object with "
                "source_entity_id: null, target_entity_id: null, and a short reason. Otherwise "
                "return exactly one flat JSON object with these required keys: "
                "source_entity_id, target_entity_id, relationship_type, evidence_quote, "
                "rationale, suggested_confidence. relationship_type must be one of "
                "manufacturing_dependency, equipment_dependency, packaging_dependency, "
                "customer_concentration, competitive_substitution, ip_or_license, or "
                "geographic_or_regulatory. evidence_quote must be an exact quote from the "
                "passage and suggested_confidence must be a number from 0 to 1. Do not nest "
                "the response or omit any required key. Graph direction is always upstream "
                "supplier/cause to downstream dependent: if NVIDIA says it relies on TSMC, "
                "use source_entity_id TSM and target_entity_id NVDA."
            ),
            user=(
                f"Known entity IDs: {sorted(self._known_entities)}\n"
                f"Filing issuer entity ID: {issuer_entity_id or 'not supplied'}\n"
                "When supplied, the filing's first-person references (we, our, us) refer "
                "to that issuer entity ID.\n"
                f"Passage: {passage.text}"
            ),
        )
        if not isinstance(raw, dict):
            raise ValueError("model response must be a JSON object")
        if raw.get("source_entity_id") is None and raw.get("target_entity_id") is None:
            return NoEdgeProposal(
                reason=str(raw.get("reason", "no supported relationship in passage")),
                passage=passage,
            )
        raw["passage"] = passage.model_dump(mode="json")
        try:
            return EdgeProposal.model_validate(raw)
        except ValueError as error:
            raise ValueError(
                "model edge proposal failed contract validation; proposal was not retained"
            ) from error


class EvidenceValidator:
    """Independent deterministic guard: exact evidence and entity/taxonomy checks."""

    def __init__(self, known_entities: set[str]) -> None:
        self._known_entities = known_entities

    def validate(self, proposal: EdgeProposal) -> EvidenceValidationReport:
        reasons: list[str] = []
        if proposal.source_entity_id not in self._known_entities:
            reasons.append("source entity is not in the approved domain registry")
        if proposal.target_entity_id not in self._known_entities:
            reasons.append("target entity is not in the approved domain registry")
        if proposal.source_entity_id == proposal.target_entity_id:
            reasons.append("source and target entities cannot be identical")
        if proposal.evidence_quote.lower() not in proposal.passage.text.lower():
            reasons.append("evidence quote is not present in the supplied passage")
        if reasons:
            return EvidenceValidationReport(
                proposal_id=proposal.id, verdict="fail", reasons=reasons
            )
        return EvidenceValidationReport(
            proposal_id=proposal.id,
            verdict="pass",
            reasons=["quote, entities, and passage provenance passed deterministic checks"],
        )
