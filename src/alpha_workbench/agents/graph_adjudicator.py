"""Bounded model-assisted maintenance of immutable supply-chain snapshots."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ..evidence import EventSignal, EvidenceObservation, TextEvidence
from ..graph_registry import (
    EntityRegistry,
    GraphEvidence,
    GraphPublisher,
    GraphSnapshot,
    ReviewDecision,
    ReviewedGraphEdge,
)
from ..llm.models import LLMClient

AdjudicationAction = Literal[
    "approve_edge",
    "update_state",
    "retire_edge",
    "hold",
    "reject",
]
RelationshipType = Literal[
    "manufacturing_dependency",
    "equipment_dependency",
    "packaging_dependency",
    "customer_concentration",
    "competitive_substitution",
    "ip_or_license",
    "geographic_or_regulatory",
]


class EdgeStateDelta(BaseModel):
    """Model suggestions, bounded before they can affect a graph snapshot."""

    dependency_strength: float = Field(default=0, ge=-1, le=1)
    substitutability: float = Field(default=0, ge=-1, le=1)
    confidence: float = Field(default=0, ge=-1, le=1)
    capacity_stress: float = Field(default=0, ge=-1, le=1)
    geographic_regulatory_stress: float = Field(default=0, ge=-1, le=1)


class GraphAdjudication(BaseModel):
    action: AdjudicationAction
    upstream_entity_id: str | None = None
    downstream_entity_id: str | None = None
    relationship_type: RelationshipType | None = None
    state_delta: EdgeStateDelta = Field(default_factory=EdgeStateDelta)
    supporting_observation_ids: list[UUID] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def edge_actions_require_a_complete_relationship(self) -> GraphAdjudication:
        if self.action in {"approve_edge", "update_state", "retire_edge"}:
            required = (
                self.upstream_entity_id,
                self.downstream_entity_id,
                self.relationship_type,
            )
            if any(value is None for value in required):
                raise ValueError("edge actions require entities and relationship_type")
            if not self.supporting_observation_ids:
                raise ValueError("edge actions require supporting observations")
        return self


class GraphAdjudicationReport(BaseModel):
    as_of_time: datetime
    decisions: list[GraphAdjudication]
    published_snapshot_id: str | None = None
    held_observation_ids: list[UUID] = Field(default_factory=list)


_TIER_RELIABILITY = {
    "primary": 0.90,
    "official": 0.75,
    "discovery": 0.35,
    "market_data": 0.50,
}
_MAX_STATE_MOVE = 0.20
_STATE_FRESHNESS_HALF_LIFE_DAYS = 180.0


class GraphAdjudicatorAgent:
    """Produces constrained graph decisions; GraphPublisher owns persistence."""

    name = "graph_adjudicator"

    def __init__(self, llm: LLMClient, registry: EntityRegistry, publisher: GraphPublisher) -> None:
        self._llm = llm
        self._registry = registry
        self._publisher = publisher

    def adjudicate(
        self,
        *,
        observations: list[EvidenceObservation],
        current_snapshot: GraphSnapshot,
        as_of_time: datetime,
        next_snapshot_id: str,
    ) -> tuple[GraphSnapshot, GraphAdjudicationReport]:
        """Create a next snapshot in memory; callers decide whether to publish it."""

        held: list[UUID] = []
        eligible: list[EvidenceObservation] = []
        for observation in observations:
            if observation.document.available_at <= as_of_time:
                eligible.append(observation)
            else:
                held.append(observation.observation_id)
        clusters: dict[tuple[str, ...], list[EvidenceObservation]] = {}
        for observation in eligible:
            resolved_entities = self._resolve_entities(observation)
            if len(resolved_entities) < 2:
                held.append(observation.observation_id)
                continue
            clusters.setdefault(tuple(sorted(resolved_entities)), []).append(observation)

        edges = self._decay_edges(
            current_snapshot.edges, current_snapshot.created_at, as_of_time
        )
        decisions: list[GraphAdjudication] = []
        for resolved_entity_tuple, cluster in clusters.items():
            decision = self._decide_cluster(cluster, set(resolved_entity_tuple))
            decision = self._apply_discovery_guard(decision, cluster)
            decisions.append(decision)
            if decision.action in {"hold", "reject"}:
                held.extend(decision.supporting_observation_ids)
                continue
            supporting = [
                observation
                for observation in cluster
                if observation.observation_id in decision.supporting_observation_ids
            ]
            edges = self._apply_decision(edges, decision, supporting, as_of_time)
        snapshot = self._publisher.build_snapshot(
            snapshot_id=next_snapshot_id, created_at=as_of_time, edges=edges
        )
        return snapshot, GraphAdjudicationReport(
            as_of_time=as_of_time,
            decisions=decisions,
            published_snapshot_id=snapshot.snapshot_id,
            held_observation_ids=held,
        )

    def adjudicate_and_publish(
        self,
        *,
        observations: list[EvidenceObservation],
        current_snapshot: GraphSnapshot,
        as_of_time: datetime,
        next_snapshot_id: str,
        snapshot_path: Path,
    ) -> GraphAdjudicationReport:
        """Publish one new immutable snapshot; existing snapshots cannot be changed."""

        snapshot, report = self.adjudicate(
            observations=observations,
            current_snapshot=current_snapshot,
            as_of_time=as_of_time,
            next_snapshot_id=next_snapshot_id,
        )
        self._publisher.publish_new(snapshot_path, snapshot)
        return report

    def _resolve_entities(self, observation: EvidenceObservation) -> set[str]:
        resolved = set(observation.mentioned_entity_ids)
        payload = observation.payload
        if isinstance(payload, TextEvidence):
            text = payload.text.lower()
            for entity in self._registry.entities:
                if any(alias.lower() in text for alias in entity.aliases):
                    resolved.add(entity.entity_id)
        return resolved.intersection(self._registry.entity_ids)

    def _decide_cluster(
        self, cluster: list[EvidenceObservation], resolved_entities: set[str]
    ) -> GraphAdjudication:
        supported = [
            observation
            for observation in cluster
            if isinstance(observation.payload, (TextEvidence, EventSignal))
        ]
        if not supported:
            return GraphAdjudication(
                action="hold",
                supporting_observation_ids=[item.observation_id for item in cluster],
                rationale="observation type does not independently establish a relationship",
            )
        evidence_parts: list[str] = []
        for observation in supported:
            payload = observation.payload
            if isinstance(payload, TextEvidence):
                content = payload.text
            elif isinstance(payload, EventSignal):
                content = payload.summary
            else:  # guarded by ``supported`` above
                continue
            evidence_parts.append(
                f"Observation {observation.observation_id} "
                f"({observation.document.source_tier}): {content}"
            )
        evidence_text = "\n\n".join(evidence_parts)
        raw = self._llm.complete_json(
            system=(
                "You are a graph adjudicator. Use only the supplied observation. Return one "
                "flat JSON GraphAdjudication. Graph direction is upstream supplier or cause to "
                "downstream dependent. You may approve a relationship only when the text "
                "directly supports it. State deltas must be between -1 and 1. Otherwise choose "
                "hold or reject. Never invent entities, evidence, or relationship types."
            ),
            user=(
                f"Approved entity IDs: {sorted(resolved_entities)}\n"
                f"Allowed observation IDs: {[str(item.observation_id) for item in supported]}\n"
                f"Evidence: {evidence_text}"
            ),
        )
        if not isinstance(raw, dict):
            raise ValueError("graph adjudicator model response must be a JSON object")
        raw.setdefault(
            "supporting_observation_ids", [str(item.observation_id) for item in supported]
        )
        decision = GraphAdjudication.model_validate(raw)
        allowed_ids = {item.observation_id for item in supported}
        if not set(decision.supporting_observation_ids).issubset(allowed_ids):
            raise ValueError("decision referenced an observation outside its adjudication cluster")
        return decision

    @staticmethod
    def _apply_discovery_guard(
        decision: GraphAdjudication, cluster: list[EvidenceObservation]
    ) -> GraphAdjudication:
        distinct_sources = {item.document.source_url for item in cluster}
        has_strong_source = any(
            item.document.source_tier in {"primary", "official"} for item in cluster
        )
        if (
            decision.action == "approve_edge"
            and not has_strong_source
            and len(distinct_sources) < 2
        ):
            return decision.model_copy(
                update={
                    "action": "hold",
                    "rationale": "single discovery observation requires corroboration",
                }
            )
        return decision

    def _apply_decision(
        self,
        edges: list[ReviewedGraphEdge],
        decision: GraphAdjudication,
        observations: list[EvidenceObservation],
        as_of_time: datetime,
    ) -> list[ReviewedGraphEdge]:
        assert decision.upstream_entity_id is not None
        assert decision.downstream_entity_id is not None
        assert decision.relationship_type is not None
        key = (
            decision.upstream_entity_id,
            decision.downstream_entity_id,
            decision.relationship_type,
        )
        index = next(
            (
                position
                for position, edge in enumerate(edges)
                if (
                    edge.upstream_entity_id,
                    edge.downstream_entity_id,
                    edge.relationship_type,
                )
                == key
            ),
            None,
        )
        if decision.action == "retire_edge":
            if index is None:
                return edges
            edges[index] = edges[index].model_copy(update={"effective_to": as_of_time})
            return edges
        if decision.action == "approve_edge" and index is None:
            edges.append(self._new_edge(decision, observations, as_of_time))
            return edges
        if decision.action == "update_state" and index is not None:
            edges[index] = self._updated_edge(edges[index], decision, observations, as_of_time)
        return edges

    def _new_edge(
        self,
        decision: GraphAdjudication,
        observations: list[EvidenceObservation],
        at: datetime,
    ) -> ReviewedGraphEdge:
        evidence = self._strongest_evidence(observations, at)
        factor = self._evidence_factor(observations, at)
        delta = decision.state_delta
        strength = self._clamp(0.50 + self._bounded_move(delta.dependency_strength, factor))
        substitution = self._clamp(0.50 + self._bounded_move(delta.substitutability, factor))
        confidence = self._clamp(factor)
        assert decision.upstream_entity_id is not None
        assert decision.downstream_entity_id is not None
        assert decision.relationship_type is not None
        edge_material = (
            f"{decision.upstream_entity_id}:{decision.downstream_entity_id}:"
            f"{decision.relationship_type}:{evidence.observation_id}"
        )
        return ReviewedGraphEdge(
            edge_id="adjudicated-" + hashlib.sha256(edge_material.encode()).hexdigest()[:20],
            upstream_entity_id=decision.upstream_entity_id,
            downstream_entity_id=decision.downstream_entity_id,
            relationship_type=decision.relationship_type,
            dependency_strength=strength,
            substitutability=substitution,
            confidence=confidence,
            capacity_stress=self._clamp(self._bounded_move(delta.capacity_stress, factor)),
            geographic_regulatory_stress=self._clamp(
                self._bounded_move(delta.geographic_regulatory_stress, factor)
            ),
            freshness=self._freshness(observations, at),
            evidence_support=factor,
            effective_from=at,
            evidence=self._graph_evidence(evidence),
            review=ReviewDecision(
                reviewed_by="graph_adjudicator_agent",
                reviewed_at=at,
                decision="approved",
                rationale=decision.rationale,
            ),
        )

    def _updated_edge(
        self,
        edge: ReviewedGraphEdge,
        decision: GraphAdjudication,
        observations: list[EvidenceObservation],
        at: datetime,
    ) -> ReviewedGraphEdge:
        evidence = self._strongest_evidence(observations, at)
        factor = self._evidence_factor(observations, at)
        delta = decision.state_delta
        return edge.model_copy(
            update={
                "dependency_strength": self._clamp(
                    edge.dependency_strength + self._bounded_move(delta.dependency_strength, factor)
                ),
                "substitutability": self._clamp(
                    edge.substitutability + self._bounded_move(delta.substitutability, factor)
                ),
                "confidence": self._clamp(
                    edge.confidence + self._bounded_move(delta.confidence, factor)
                ),
                "capacity_stress": self._clamp(
                    edge.capacity_stress + self._bounded_move(delta.capacity_stress, factor)
                ),
                "geographic_regulatory_stress": self._clamp(
                    edge.geographic_regulatory_stress
                    + self._bounded_move(delta.geographic_regulatory_stress, factor)
                ),
                "freshness": self._freshness(observations, at),
                "evidence_support": self._clamp(edge.evidence_support + factor),
                "evidence": self._graph_evidence(evidence),
                "review": ReviewDecision(
                    reviewed_by="graph_adjudicator_agent",
                    reviewed_at=at,
                    decision="approved",
                    rationale=decision.rationale,
                ),
            }
        )

    @staticmethod
    def _graph_evidence(observation: EvidenceObservation) -> GraphEvidence:
        payload = observation.payload
        quote = payload.exact_quote if isinstance(payload, TextEvidence) else str(payload)
        document = observation.document
        return GraphEvidence(
            source_url=document.source_url,
            filing_accession=document.external_id or str(observation.observation_id),
            filing_date=document.available_at,
            snapshot_sha256=document.content_sha256,
            evidence_quote=quote,
            extraction_proposal_id=str(observation.observation_id),
            validator_verdict="pass",
        )

    @staticmethod
    def _bounded_move(suggested_delta: float, factor: float) -> float:
        return max(-_MAX_STATE_MOVE, min(_MAX_STATE_MOVE, suggested_delta * factor))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _evidence_factor(observations: list[EvidenceObservation], at: datetime) -> float:
        return min(
            1.0,
            sum(
                GraphAdjudicatorAgent._single_evidence_factor(observation, at)
                for observation in observations
            ),
        )

    @staticmethod
    def _single_evidence_factor(observation: EvidenceObservation, at: datetime) -> float:
        age_days = max(0.0, (at - observation.document.available_at).total_seconds() / 86_400)
        half_life_days = 180.0 if observation.document.source_tier != "discovery" else 30.0
        freshness = math.exp(-math.log(2) * age_days / half_life_days)
        return _TIER_RELIABILITY[observation.document.source_tier] * freshness

    @staticmethod
    def _freshness(observations: list[EvidenceObservation], at: datetime) -> float:
        if not observations:
            return 0.0
        return max(
            GraphAdjudicatorAgent._single_evidence_factor(observation, at)
            / _TIER_RELIABILITY[observation.document.source_tier]
            for observation in observations
        )

    @staticmethod
    def _decay_edges(
        edges: list[ReviewedGraphEdge], prior_snapshot_time: datetime, at: datetime
    ) -> list[ReviewedGraphEdge]:
        """Age evidence support without weakening a durable relationship itself."""

        elapsed_days = max(0.0, (at - prior_snapshot_time).total_seconds() / 86_400)
        decay = math.exp(-math.log(2) * elapsed_days / _STATE_FRESHNESS_HALF_LIFE_DAYS)
        return [
            edge.model_copy(
                update={
                    "freshness": edge.freshness * decay,
                    "evidence_support": edge.evidence_support * decay,
                    "capacity_stress": edge.capacity_stress * decay,
                    "geographic_regulatory_stress": edge.geographic_regulatory_stress
                    * decay,
                }
            )
            for edge in edges
        ]

    @staticmethod
    def _strongest_evidence(
        observations: list[EvidenceObservation], at: datetime
    ) -> EvidenceObservation:
        if not observations:
            raise ValueError("a graph decision requires at least one supporting observation")
        return max(
            observations,
            key=lambda observation: GraphAdjudicatorAgent._single_evidence_factor(
                observation, at
            ),
        )
