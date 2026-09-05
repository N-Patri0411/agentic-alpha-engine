"""LLM-assisted high-recall relationship discovery outside the anchor registry."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..candidate_graph import DiscoveredRelationship
from ..llm.models import LLMClient
from .sections import DocumentPassage


class OpenWorldExtractionResult(BaseModel):
    relationships: list[DiscoveredRelationship] = Field(default_factory=list, max_length=5)


class OpenWorldRelationshipExtractor:
    """Find up to five source-bound, one-hop candidate relationships per passage."""

    def __init__(self, llm: LLMClient, anchor_names: dict[str, tuple[str, ...]]) -> None:
        self._llm = llm
        self._anchor_names = anchor_names

    def extract(self, passage: DocumentPassage, *, available_at: str) -> OpenWorldExtractionResult:
        raw = self._llm.complete_json(
            system=(
                "Extract only directly stated company relationships from the supplied passage. "
                "Return exactly one JSON object with a relationships array containing "
                "zero to five objects. Each object requires source_entity_name, "
                "target_entity_name, relationship_type, "
                "evidence_quote, rationale, and suggested_confidence. "
                "relationship_type must be one of "
                "manufacturing_dependency, equipment_dependency, packaging_dependency, "
                "customer_concentration, competitive_substitution, ip_or_license, "
                "geographic_or_regulatory, or strategic_collaboration. A competitor "
                "statement may use competitive_substitution. A generic partnership without "
                "a named commercial activity may use strategic_collaboration, never "
                "manufacturing_dependency. Do not infer unstated customers, suppliers, "
                "competitors, or relationship weights. Every quote must be exact."
            ),
            user=(
                f"Anchor companies and aliases: {self._anchor_names}\n"
                f"Available at: {available_at}\n"
                f"Source URL: {passage.source_url}\n"
                f"Passage: {passage.text}"
            ),
        )
        if not isinstance(raw, dict):
            raise ValueError("model response must be a JSON object")
        raw_relationships = raw.get("relationships", [])
        if not isinstance(raw_relationships, list):
            raise ValueError("relationships must be a JSON array")
        relationships = [
            DiscoveredRelationship.model_validate(
                {
                    **item,
                    "passage_text": passage.text,
                    "source_url": passage.source_url,
                    "available_at": available_at,
                }
            )
            for item in raw_relationships
            if isinstance(item, dict)
        ]
        return OpenWorldExtractionResult(relationships=relationships)
