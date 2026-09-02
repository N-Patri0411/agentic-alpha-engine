"""Stable graph-view data that a future Cytoscape React component can render."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..graph_registry import EntityRegistry, GraphSnapshot
from ..models import ScenarioResult


class ScenarioGraphNode(BaseModel):
    id: str
    label: str
    tradeable: bool
    severity: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)


class ScenarioGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    dependency_strength: float = Field(ge=0, le=1)
    substitutability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    freshness: float = Field(ge=0, le=1)
    evidence_url: str


class ScenarioGraphView(BaseModel):
    snapshot_id: str
    as_of_time: str
    nodes: list[ScenarioGraphNode]
    edges: list[ScenarioGraphEdge]


def build_scenario_graph_view(
    *, registry: EntityRegistry, snapshot: GraphSnapshot, scenario: ScenarioResult
) -> ScenarioGraphView:
    impacts = {impact.entity: impact for impact in scenario.impacts}
    nodes = []
    for entity in registry.entities:
        impact = impacts.get(entity.entity_id)
        severity = scenario.shock_severity if entity.entity_id == scenario.shock_entity else 0.0
        confidence = 1.0 if entity.entity_id == scenario.shock_entity else 0.0
        if impact is not None:
            severity = impact.severity
            confidence = impact.confidence
        nodes.append(
            ScenarioGraphNode(
                id=entity.entity_id,
                label=entity.legal_name,
                tradeable=entity.tradeable,
                severity=severity,
                confidence=confidence,
            )
        )
    return ScenarioGraphView(
        snapshot_id=snapshot.snapshot_id,
        as_of_time=scenario.as_of_time.isoformat(),
        nodes=nodes,
        edges=[
            ScenarioGraphEdge(
                id=edge.edge_id,
                source=edge.upstream_entity_id,
                target=edge.downstream_entity_id,
                relationship_type=edge.relationship_type,
                dependency_strength=edge.dependency_strength,
                substitutability=edge.substitutability,
                confidence=edge.confidence,
                freshness=edge.freshness,
                evidence_url=edge.evidence.source_url,
            )
            for edge in snapshot.edges
        ],
    )
