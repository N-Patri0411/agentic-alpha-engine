"""Reviewed, immutable supply-chain graph records and scenario scorer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .graph import SupplyChainEdge, SupplyChainGraph
from .models import ScenarioResult


class EntityRecord(BaseModel):
    """Canonical company identity, independent of whether it is tradeable."""

    entity_id: str = Field(min_length=1)
    legal_name: str = Field(min_length=1)
    aliases: list[str] = Field(min_length=1)
    cik: str | None = None
    ticker: str | None = None
    tradeable: bool


class EntityRegistry(BaseModel):
    registry_id: str = Field(min_length=1)
    schema_version: Literal["1"] = "1"
    created_at: datetime
    entities: list[EntityRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def entity_ids_are_unique(self) -> EntityRegistry:
        ids = [entity.entity_id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("entity registry contains duplicate entity IDs")
        return self

    @classmethod
    def from_json(cls, path: Path) -> EntityRegistry:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @property
    def entity_ids(self) -> set[str]:
        return {entity.entity_id for entity in self.entities}


class GraphEvidence(BaseModel):
    """Verbatim source receipt supporting one reviewed graph edge."""

    source_url: str
    filing_accession: str
    filing_date: datetime
    snapshot_sha256: str = Field(min_length=64, max_length=64)
    evidence_quote: str = Field(min_length=10)
    extraction_proposal_id: str = Field(min_length=1)
    validator_verdict: Literal["pass"]


class ReviewDecision(BaseModel):
    """Governed decision required before a draft can enter an immutable snapshot."""

    reviewed_by: str = Field(min_length=1)
    reviewed_at: datetime
    decision: Literal["approved", "rejected"]
    rationale: str = Field(min_length=10)


class ReviewedGraphEdge(BaseModel):
    """A directional scenario edge: upstream disruption can affect downstream."""

    edge_id: str = Field(min_length=1)
    upstream_entity_id: str = Field(min_length=1)
    downstream_entity_id: str = Field(min_length=1)
    relationship_type: Literal[
        "manufacturing_dependency",
        "equipment_dependency",
        "packaging_dependency",
        "customer_concentration",
        "competitive_substitution",
        "ip_or_license",
        "geographic_or_regulatory",
    ]
    dependency_strength: float = Field(ge=0, le=1)
    substitutability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    capacity_stress: float = Field(default=0, ge=0, le=1)
    geographic_regulatory_stress: float = Field(default=0, ge=0, le=1)
    freshness: float = Field(default=1, ge=0, le=1)
    evidence_support: float = Field(default=0, ge=0, le=1)
    effective_from: datetime
    effective_to: datetime | None = None
    evidence: GraphEvidence
    review: ReviewDecision

    @model_validator(mode="after")
    def approved_and_non_self_referential(self) -> ReviewedGraphEdge:
        if self.upstream_entity_id == self.downstream_entity_id:
            raise ValueError("graph edge cannot connect an entity to itself")
        if self.review.decision != "approved":
            raise ValueError("only approved edges may appear in a graph snapshot")
        return self


def _edges_digest(edges: list[ReviewedGraphEdge]) -> str:
    payload = [edge.model_dump(mode="json") for edge in edges]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_edges_digest(edges: list[ReviewedGraphEdge]) -> str:
    """Validate schema-v1 snapshots created before temporal state fields existed."""

    temporal_fields = {
        "capacity_stress",
        "geographic_regulatory_stress",
        "freshness",
        "evidence_support",
    }
    payload = [edge.model_dump(mode="json", exclude=temporal_fields) for edge in edges]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GraphSnapshot(BaseModel):
    """Append-only reviewed graph version, verified against its edge digest."""

    snapshot_id: str = Field(min_length=1)
    schema_version: Literal["1"] = "1"
    created_at: datetime
    entity_registry_id: str = Field(min_length=1)
    edges: list[ReviewedGraphEdge] = Field(min_length=1)
    edges_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def digest_matches_edges(self) -> GraphSnapshot:
        if self.edges_sha256 not in {_edges_digest(self.edges), _legacy_edges_digest(self.edges)}:
            raise ValueError("graph snapshot edge digest does not match its contents")
        return self

    @classmethod
    def from_json(cls, path: Path) -> GraphSnapshot:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class GraphPublisher:
    """Creates a new snapshot only from reviewed, registry-valid edges."""

    def __init__(self, registry: EntityRegistry) -> None:
        self._registry = registry

    def build_snapshot(
        self, *, snapshot_id: str, created_at: datetime, edges: list[ReviewedGraphEdge]
    ) -> GraphSnapshot:
        if not edges:
            raise ValueError("a graph snapshot requires at least one reviewed edge")
        for edge in edges:
            edge_entities = {edge.upstream_entity_id, edge.downstream_entity_id}
            unknown = edge_entities - self._registry.entity_ids
            if unknown:
                raise ValueError(f"edge references unregistered entity IDs: {sorted(unknown)}")
        return GraphSnapshot(
            snapshot_id=snapshot_id,
            created_at=created_at,
            entity_registry_id=self._registry.registry_id,
            edges=edges,
            edges_sha256=_edges_digest(edges),
        )

    def publish_new(self, path: Path, snapshot: GraphSnapshot) -> None:
        """Write once: existing snapshots are immutable and cannot be overwritten."""

        if path.exists():
            raise FileExistsError(f"refusing to overwrite immutable snapshot: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")


class RippleRiskScorer:
    """Stable deterministic graph tool used by the future Extraction Agent."""

    def __init__(self, snapshot: GraphSnapshot) -> None:
        self._snapshot = snapshot

    @classmethod
    def from_json(cls, path: Path) -> RippleRiskScorer:
        return cls(GraphSnapshot.from_json(path))

    def score(
        self, *, shock_entity_id: str, severity: float, as_of_time: datetime, max_hops: int = 3
    ) -> ScenarioResult:
        graph = SupplyChainGraph(
            [
                SupplyChainEdge(
                    source=edge.upstream_entity_id,
                    target=edge.downstream_entity_id,
                    relationship=edge.relationship_type,
                    source_url=edge.evidence.source_url,
                    weight=min(
                        1.0,
                        edge.dependency_strength
                        * edge.freshness
                        * (
                            1.0
                            + 0.5 * edge.capacity_stress
                            + 0.5 * edge.geographic_regulatory_stress
                        ),
                    ),
                    substitutability=edge.substitutability,
                    confidence=edge.confidence,
                    effective_from=edge.effective_from,
                    effective_to=edge.effective_to,
                )
                for edge in self._snapshot.edges
            ]
        )
        return graph.scenario(shock_entity_id, severity, as_of_time, max_hops=max_hops)
