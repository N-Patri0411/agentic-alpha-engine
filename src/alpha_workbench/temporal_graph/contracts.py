"""Immutable contracts for temporal, evidence-backed graph snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from alpha_workbench.product.contracts import ContractBase

NodeKind = Literal[
    "entity",
    "instrument",
    "industry",
    "geography",
    "commodity",
    "event",
    "regulator",
    "technology",
    "external_context",
    "other",
]
RelationSemantics = Literal["directed", "symmetric"]
LifecycleStatus = Literal["proposed", "active", "deprecated", "retracted"]
EligibilityStatus = Literal["eligible", "ineligible", "review_required"]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("temporal graph timestamps must be timezone-aware")
    return value


class GraphNode(ContractBase):
    """A typed graph node; entity and instrument identities stay distinct."""

    node_id: str = Field(min_length=1)
    kind: NodeKind
    label: str = Field(min_length=1)
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    lifecycle_status: LifecycleStatus = "active"
    strategy_eligible: bool = False


class GraphRelationship(ContractBase):
    """Stable relation semantics, separate from time-varying edge state."""

    relationship_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    semantics: RelationSemantics
    description: str = ""


class GraphEdgeState(ContractBase):
    """An immutable, bitemporal assertion linking two graph nodes."""

    edge_id: str = Field(min_length=1)
    relationship_id: str = Field(min_length=1)
    source_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    effective_from: datetime
    effective_to: datetime | None = None
    knowledge_from: datetime
    knowledge_to: datetime | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    economic_exposure: float = Field(ge=0)
    propagation_coefficient: float = Field(ge=0, le=1)
    lifecycle_status: LifecycleStatus = "active"
    strategy_eligible: EligibilityStatus = "review_required"
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("effective_from", "effective_to", "knowledge_from", "knowledge_to")
    @classmethod
    def timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def intervals_are_ordered(self) -> GraphEdgeState:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        if self.knowledge_to is not None and self.knowledge_to <= self.knowledge_from:
            raise ValueError("knowledge_to must be later than knowledge_from")
        if self.source_node_id == self.target_node_id:
            raise ValueError("self edges are not supported")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence IDs must be unique per edge state")
        return self


class TemporalGraphSnapshot(ContractBase):
    """Full immutable graph snapshot for one workspace and two as-of clocks."""

    snapshot_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    universe_id: str = Field(min_length=1)
    universe_instrument_ids: tuple[str, ...] = Field(min_length=1)
    parent_snapshot_id: str | None = None
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    as_of_time: datetime
    knowledge_time: datetime
    nodes: tuple[GraphNode, ...] = ()
    relationships: tuple[GraphRelationship, ...] = ()
    edge_states: tuple[GraphEdgeState, ...] = ()
    source_run_id: str | None = None

    @field_validator("published_at", "as_of_time", "knowledge_time")
    @classmethod
    def snapshot_timestamps_are_aware(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def validate_graph(self) -> TemporalGraphSnapshot:
        node_ids = [node.node_id for node in self.nodes]
        relation_ids = [rel.relationship_id for rel in self.relationships]
        edge_ids = [edge.edge_id for edge in self.edge_states]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("snapshot contains duplicate node IDs")
        if len(self.universe_instrument_ids) != len(set(self.universe_instrument_ids)):
            raise ValueError("snapshot contains duplicate universe instrument IDs")
        nodes_by_id = {node.node_id: node for node in self.nodes}
        for instrument_id in self.universe_instrument_ids:
            if instrument_id not in nodes_by_id or nodes_by_id[instrument_id].kind != "instrument":
                raise ValueError(f"universe instrument {instrument_id} has no instrument node")
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("snapshot contains duplicate relationship IDs")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("snapshot contains duplicate edge IDs")
        nodes, relations = set(node_ids), {rel.relationship_id: rel for rel in self.relationships}
        seen_pairs: dict[tuple[str, str, str], list[GraphEdgeState]] = {}
        for edge in self.edge_states:
            if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                raise ValueError(f"edge {edge.edge_id} has an unregistered endpoint")
            relationship = relations.get(edge.relationship_id)
            if relationship is None:
                raise ValueError(f"edge {edge.edge_id} has an unregistered relationship")
            pair: tuple[str, str, str] = (
                edge.relationship_id,
                edge.source_node_id,
                edge.target_node_id,
            )
            if relationship.semantics == "symmetric":
                pair = (
                    edge.relationship_id,
                    min(edge.source_node_id, edge.target_node_id),
                    max(edge.source_node_id, edge.target_node_id),
                )
            for prior in seen_pairs.get(pair, []):
                effective_overlap = (
                    prior.effective_to is None or edge.effective_from < prior.effective_to
                ) and (edge.effective_to is None or prior.effective_from < edge.effective_to)
                knowledge_overlap = (
                    prior.knowledge_to is None or edge.knowledge_from < prior.knowledge_to
                ) and (edge.knowledge_to is None or prior.knowledge_from < edge.knowledge_to)
                if effective_overlap and knowledge_overlap:
                    raise ValueError(
                        "snapshot contains overlapping bitemporal intervals for edge endpoints"
                    )
            seen_pairs.setdefault(pair, []).append(edge)
        return self

    @property
    def content_digest(self) -> str:
        return self.content_sha256()

    def visible_edge_states(
        self, *, as_of_time: datetime | None = None, knowledge_time: datetime | None = None
    ) -> tuple[GraphEdgeState, ...]:
        """Return states visible at both effective and knowledge clocks."""
        effective = _aware(as_of_time or self.as_of_time)
        known = _aware(knowledge_time or self.knowledge_time)
        return tuple(
            edge
            for edge in self.edge_states
            if edge.effective_from <= effective
            and (edge.effective_to is None or effective < edge.effective_to)
            and edge.knowledge_from <= known
            and (edge.knowledge_to is None or known < edge.knowledge_to)
        )


class GraphSnapshotDiff(ContractBase):
    """Deterministic change summary between two full graph snapshots."""

    prior_snapshot_id: str = Field(min_length=1)
    current_snapshot_id: str = Field(min_length=1)
    prior_universe_id: str = Field(min_length=1)
    current_universe_id: str = Field(min_length=1)
    added_universe_instrument_ids: tuple[str, ...] = ()
    removed_universe_instrument_ids: tuple[str, ...] = ()
    added_node_ids: tuple[str, ...] = ()
    removed_node_ids: tuple[str, ...] = ()
    changed_node_ids: tuple[str, ...] = ()
    added_relationship_ids: tuple[str, ...] = ()
    removed_relationship_ids: tuple[str, ...] = ()
    changed_relationship_ids: tuple[str, ...] = ()
    added_edge_ids: tuple[str, ...] = ()
    removed_edge_ids: tuple[str, ...] = ()
    changed_edge_ids: tuple[str, ...] = ()


class GraphPublicationReceipt(ContractBase):
    """Receipt for one immutable snapshot publication."""

    snapshot_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    published_at: datetime

    @field_validator("published_at")
    @classmethod
    def receipt_timestamp_is_aware(cls, value: datetime) -> datetime:
        return _aware(value)
