"""One-hop evidence graph for discovered entities and unapproved relationships."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .graph_registry import EntityRegistry

CandidateRelationshipType = Literal[
    "manufacturing_dependency",
    "equipment_dependency",
    "packaging_dependency",
    "customer_concentration",
    "competitive_substitution",
    "ip_or_license",
    "geographic_or_regulatory",
    "strategic_collaboration",
]
_SCENARIO_ELIGIBLE_TYPES = {
    "manufacturing_dependency",
    "equipment_dependency",
    "packaging_dependency",
}


class DiscoveredRelationship(BaseModel):
    """A source-bound candidate; it is not a scenario edge or graph update."""

    source_entity_name: str = Field(min_length=1)
    target_entity_name: str = Field(min_length=1)
    relationship_type: CandidateRelationshipType
    evidence_quote: str = Field(min_length=10)
    passage_text: str = Field(min_length=10)
    source_url: str = Field(min_length=1)
    available_at: datetime
    rationale: str = Field(min_length=1)
    suggested_confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def evidence_must_be_verbatim(self) -> DiscoveredRelationship:
        if self.evidence_quote.lower() not in self.passage_text.lower():
            raise ValueError("evidence_quote must be present in passage_text")
        if self.source_entity_name.casefold() == self.target_entity_name.casefold():
            raise ValueError("candidate relationship cannot be self-referential")
        return self


class CandidateGraphEntity(BaseModel):
    entity_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    kind: Literal["anchor", "discovered"]
    tradeable: bool = False
    discovery_depth: Literal[0, 1]
    status: Literal["approved", "candidate"]


class CandidateGraphEdge(BaseModel):
    source_entity_id: str = Field(min_length=1)
    target_entity_id: str = Field(min_length=1)
    relationship_type: CandidateRelationshipType
    status: Literal["candidate"] = "candidate"
    scenario_eligible: bool
    evidence_quote: str = Field(min_length=10)
    source_url: str = Field(min_length=1)
    available_at: datetime
    rationale: str = Field(min_length=1)
    suggested_confidence: float = Field(ge=0, le=1)


class CandidateEvidenceGraph(BaseModel):
    """A bounded, inspectable layer before graph adjudication/promotion."""

    registry_id: str
    nodes: list[CandidateGraphEntity]
    edges: list[CandidateGraphEdge]
    ignored_relationship_count: int = Field(ge=0)


class CandidateGraphBuilder:
    """Resolve anchors and add only one-hop discovered entity nodes."""

    def __init__(self, registry: EntityRegistry, *, maximum_discovered_entities: int = 30) -> None:
        if maximum_discovered_entities < 1:
            raise ValueError("maximum_discovered_entities must be positive")
        self._registry = registry
        self._maximum_discovered_entities = maximum_discovered_entities
        self._aliases = {
            alias.casefold(): entity.entity_id
            for entity in registry.entities
            for alias in (entity.entity_id, entity.legal_name, *entity.aliases)
        }

    def build(self, relationships: list[DiscoveredRelationship]) -> CandidateEvidenceGraph:
        nodes = {
            entity.entity_id: CandidateGraphEntity(
                entity_id=entity.entity_id,
                display_name=entity.legal_name,
                kind="anchor",
                tradeable=entity.tradeable,
                discovery_depth=0,
                status="approved",
            )
            for entity in self._registry.entities
        }
        edges: list[CandidateGraphEdge] = []
        edge_keys: set[tuple[str, str, str, str]] = set()
        ignored = 0
        for relationship in relationships:
            source_id, source_node = self._resolve(relationship.source_entity_name)
            target_id, target_node = self._resolve(relationship.target_entity_name)
            anchor_ids = self._registry.entity_ids
            if source_id not in anchor_ids and target_id not in anchor_ids:
                ignored += 1
                continue
            discovered = [node for node in (source_node, target_node) if node.kind == "discovered"]
            new_nodes = [node for node in discovered if node.entity_id not in nodes]
            existing_discovered = sum(node.kind == "discovered" for node in nodes.values())
            if existing_discovered + len(new_nodes) > self._maximum_discovered_entities:
                ignored += 1
                continue
            nodes[source_id] = source_node
            nodes[target_id] = target_node
            key = (
                source_id,
                target_id,
                relationship.relationship_type,
                relationship.source_url,
            )
            if key in edge_keys:
                continue
            edge_keys.add(key)
            edges.append(
                CandidateGraphEdge(
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relationship_type=relationship.relationship_type,
                    scenario_eligible=relationship.relationship_type in _SCENARIO_ELIGIBLE_TYPES,
                    evidence_quote=relationship.evidence_quote,
                    source_url=relationship.source_url,
                    available_at=relationship.available_at,
                    rationale=relationship.rationale,
                    suggested_confidence=relationship.suggested_confidence,
                )
            )
        return CandidateEvidenceGraph(
            registry_id=self._registry.registry_id,
            nodes=list(nodes.values()),
            edges=edges,
            ignored_relationship_count=ignored,
        )

    def _resolve(self, entity_name: str) -> tuple[str, CandidateGraphEntity]:
        normalized = entity_name.casefold().strip()
        resolved = self._aliases.get(normalized)
        if resolved is not None:
            entity = next(item for item in self._registry.entities if item.entity_id == resolved)
            return resolved, CandidateGraphEntity(
                entity_id=entity.entity_id,
                display_name=entity.legal_name,
                kind="anchor",
                tradeable=entity.tradeable,
                discovery_depth=0,
                status="approved",
            )
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        entity_id = f"candidate:{slug or 'unknown'}"
        return entity_id, CandidateGraphEntity(
            entity_id=entity_id,
            display_name=entity_name.strip(),
            kind="discovered",
            discovery_depth=1,
            status="candidate",
        )
