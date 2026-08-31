"""Effective-dated deterministic supply-chain scenario propagation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import ScenarioImpact, ScenarioPathEdge, ScenarioResult


@dataclass(frozen=True)
class SupplyChainEdge:
    """A sourced directed dependency relationship."""

    source: str
    target: str
    relationship: str
    source_url: str
    weight: float
    substitutability: float
    confidence: float
    effective_from: datetime
    effective_to: datetime | None = None

    def is_effective(self, as_of_time: datetime) -> bool:
        return self.effective_from <= as_of_time and (
            self.effective_to is None or as_of_time <= self.effective_to
        )

    def propagated_severity(self, incoming_severity: float) -> float:
        return incoming_severity * self.weight * (1 - self.substitutability)

    def as_path_edge(self) -> ScenarioPathEdge:
        return ScenarioPathEdge(
            source=self.source,
            target=self.target,
            relationship=self.relationship,
            source_url=self.source_url,
            edge_weight=self.weight,
            substitutability=self.substitutability,
        )


class SupplyChainGraph:
    """Small scenario graph. It is not a trained or predictive model."""

    def __init__(self, edges: list[SupplyChainEdge]) -> None:
        self._edges = edges

    @classmethod
    def from_json(cls, path: Path) -> SupplyChainGraph:
        raw_edges = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw_edges, list):
            raise ValueError("edge registry must be a JSON list")
        edges = [
            SupplyChainEdge(
                source=edge["source"],
                target=edge["target"],
                relationship=edge["relationship"],
                source_url=edge["source_url"],
                weight=float(edge["weight"]),
                substitutability=float(edge["substitutability"]),
                confidence=float(edge["confidence"]),
                effective_from=datetime.fromisoformat(edge["effective_from"]),
                effective_to=(
                    datetime.fromisoformat(edge["effective_to"])
                    if edge.get("effective_to")
                    else None
                ),
            )
            for edge in raw_edges
        ]
        for edge in edges:
            if not all(
                0 <= value <= 1 for value in (edge.weight, edge.substitutability, edge.confidence)
            ):
                raise ValueError("edge weight, substitutability, and confidence must be in [0, 1]")
        return cls(edges)

    def scenario(
        self,
        shock_entity: str,
        shock_severity: float,
        as_of_time: datetime,
        *,
        max_hops: int = 3,
    ) -> ScenarioResult:
        """Propagate a shock through effective edges while preserving the strongest path."""

        if not 0 <= shock_severity <= 1:
            raise ValueError("shock_severity must be in [0, 1]")
        if max_hops < 1:
            raise ValueError("max_hops must be at least one")
        active = [edge for edge in self._edges if edge.is_effective(as_of_time)]
        adjacency: dict[str, list[SupplyChainEdge]] = {}
        for edge in active:
            adjacency.setdefault(edge.source, []).append(edge)

        best: dict[str, tuple[float, float, list[ScenarioPathEdge]]] = {
            shock_entity: (shock_severity, 1.0, [])
        }
        frontier: list[tuple[str, float, float, list[ScenarioPathEdge], int]] = [
            (shock_entity, shock_severity, 1.0, [], 0)
        ]
        while frontier:
            entity, severity, confidence, path, hops = frontier.pop(0)
            if hops >= max_hops:
                continue
            for edge in adjacency.get(entity, []):
                propagated = edge.propagated_severity(severity)
                propagated_confidence = confidence * edge.confidence
                candidate_path = [*path, edge.as_path_edge()]
                existing = best.get(edge.target)
                if existing is not None and existing[0] >= propagated:
                    continue
                best[edge.target] = (propagated, propagated_confidence, candidate_path)
                frontier.append(
                    (edge.target, propagated, propagated_confidence, candidate_path, hops + 1)
                )

        impacts = [
            ScenarioImpact(entity=entity, severity=severity, confidence=confidence, path=path)
            for entity, (severity, confidence, path) in best.items()
            if entity != shock_entity
        ]
        impacts.sort(key=lambda impact: (-impact.severity, impact.entity))
        return ScenarioResult(
            shock_entity=shock_entity,
            shock_severity=shock_severity,
            as_of_time=as_of_time,
            impacts=impacts,
            limitations=[
                "Deterministic edge propagation is a scenario aid, not a predictive return model.",
                "Relationship weights are hypotheses that require maintained source evidence "
                "and validation.",
            ],
        )
