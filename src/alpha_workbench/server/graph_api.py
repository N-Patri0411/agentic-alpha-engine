"""REST serialization for temporal graph snapshots and refresh jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import exp, log
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from alpha_workbench.graph_pipeline.inputs import GraphInputProvider
from alpha_workbench.jobs.contracts import JobRequest
from alpha_workbench.jobs.dispatch import JobDispatcher
from alpha_workbench.persistence.repositories import ProductRepository
from alpha_workbench.temporal_graph import (
    GraphSnapshotNotFoundError,
    TemporalGraphRepository,
    TemporalGraphSnapshot,
    diff_snapshots,
)


class GraphRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str | None = None


@dataclass(slots=True)
class GraphApiDependencies:
    workspace_repository: ProductRepository
    graph_repository: TemporalGraphRepository
    input_provider: GraphInputProvider
    dispatcher: JobDispatcher


def create_graph_router(dependencies: GraphApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/workspaces/{workspace_id}/graph/snapshots")
    def list_snapshots(workspace_id: str) -> list[dict[str, Any]]:
        return [
            graph_snapshot_summary(snapshot)
            for snapshot in dependencies.graph_repository.list(workspace_id)
        ]

    @router.get("/api/graph-snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str) -> dict[str, Any]:
        try:
            snapshot = dependencies.graph_repository.get(snapshot_id)
        except GraphSnapshotNotFoundError as error:
            raise HTTPException(status_code=404, detail="graph snapshot not found") from error
        return normalize_snapshot(snapshot)

    @router.get("/api/graph-snapshots/{snapshot_id}/diff")
    def get_diff(snapshot_id: str, compare_to: str) -> dict[str, Any]:
        try:
            current = dependencies.graph_repository.get(snapshot_id)
            prior = dependencies.graph_repository.get(compare_to)
        except GraphSnapshotNotFoundError as error:
            raise HTTPException(status_code=404, detail="graph snapshot not found") from error
        if prior.workspace_id != current.workspace_id:
            raise HTTPException(
                status_code=400, detail="snapshots must belong to the same workspace"
            )
        diff = diff_snapshots(prior, current)
        return _wire_diff(diff, prior, current)

    @router.post("/api/workspaces/{workspace_id}/graph-refresh", status_code=202)
    def refresh_graph(workspace_id: str, request: GraphRefreshRequest) -> dict[str, Any]:
        try:
            workspace = dependencies.workspace_repository.latest_workspace(workspace_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="workspace not found") from error
        if not workspace.universe_id:
            raise HTTPException(status_code=409, detail="workspace has no locked universe")
        idempotency_key = request.idempotency_key or str(uuid4())
        scoped_key = f"graph-refresh:{workspace_id}:{idempotency_key}"
        existing = dependencies.dispatcher.repository.find_by_idempotency(scoped_key)
        if existing is not None:
            return existing.to_dict()
        now = datetime.now(UTC)
        job_id = str(uuid4())
        job = dependencies.dispatcher.submit(
            JobRequest(
                kind="graph-refresh",
                idempotency_key=scoped_key,
                job_id=job_id,
                payload={
                    "workspace_id": workspace_id,
                    "as_of_time": now.isoformat(),
                    "knowledge_time": now.isoformat(),
                },
            )
        )
        return job.to_dict()

    return router


def graph_snapshot_summary(snapshot: TemporalGraphSnapshot) -> dict[str, Any]:
    wire = normalize_snapshot(snapshot)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "workspace_id": snapshot.workspace_id,
        "as_of_time": snapshot.as_of_time.isoformat(),
        "created_at": snapshot.published_at.isoformat(),
        **wire["coverage"],
        "coverage": wire["coverage"],
    }


def normalize_snapshot(snapshot: TemporalGraphSnapshot) -> dict[str, Any]:
    """Project economic entity links onto locked instruments for the UI wire model."""
    nodes_by_id = {node.node_id: node for node in snapshot.nodes}
    instrument_ids = set(snapshot.universe_instrument_ids)
    entity_to_instruments: dict[str, list[str]] = {}
    for instrument_id in snapshot.universe_instrument_ids:
        instrument = nodes_by_id[instrument_id]
        entity_id = instrument.properties.get("entity_id")
        if isinstance(entity_id, str):
            entity_to_instruments.setdefault(entity_id, []).append(instrument_id)

    wire_nodes: list[dict[str, Any]] = []
    for node in snapshot.nodes:
        if node.kind == "entity":
            continue
        wire_instrument_id = node.node_id if node.kind == "instrument" else None
        wire_nodes.append(
            {
                "node_id": node.node_id,
                "node_kind": node.kind,
                "label": node.label,
                "tradeable": node.kind == "instrument" and node.node_id in instrument_ids,
                **({"instrument_id": wire_instrument_id} if wire_instrument_id else {}),
                **(
                    {"entity_id": str(node.properties.get("entity_id"))}
                    if node.properties.get("entity_id")
                    else {}
                ),
                "metadata": dict(node.properties),
            }
        )

    relationships: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    connected_instruments: set[str] = set()
    freshness_values: list[float] = []
    visible = snapshot.visible_edge_states()
    relationship_defs = {item.relationship_id: item for item in snapshot.relationships}
    for edge in visible:
        source_ids = _display_endpoints(edge.source_node_id, nodes_by_id, entity_to_instruments)
        target_ids = _display_endpoints(edge.target_node_id, nodes_by_id, entity_to_instruments)
        relation = relationship_defs[edge.relationship_id]
        freshness = _edge_freshness(edge.attributes, snapshot.as_of_time)
        freshness_values.append(freshness)
        for source_id in source_ids:
            for target_id in target_ids:
                if source_id == target_id:
                    continue
                projected_id = f"{edge.edge_id}:{source_id}>{target_id}"
                relationships.append(
                    {
                        "relationship_id": projected_id,
                        "source_node_id": source_id,
                        "target_node_id": target_id,
                        "relationship_type": relation.name,
                        "direction": relation.semantics,
                    }
                )
                states.append(
                    {
                        "relationship_id": projected_id,
                        "confidence": edge.confidence,
                        "economic_exposure": edge.economic_exposure,
                        "propagation_coefficient": edge.propagation_coefficient,
                        "freshness": freshness,
                        "strategy_eligible": (
                            edge.strategy_eligible == "eligible"
                            and edge.lifecycle_status == "active"
                        ),
                        "lifecycle_status": edge.lifecycle_status,
                        "evidence_ids": list(edge.evidence_ids),
                    }
                )
                if edge.strategy_eligible == "eligible" and edge.lifecycle_status == "active":
                    if source_id in instrument_ids:
                        connected_instruments.add(source_id)
                    if target_id in instrument_ids:
                        connected_instruments.add(target_id)

    coverage = {
        "tradeable_connected": len(connected_instruments),
        "total_tradeable": len(instrument_ids),
        "eligible_relationships": sum(item["strategy_eligible"] for item in states),
        "total_relationships": len(relationships),
        "freshness": sum(freshness_values) / len(freshness_values) if freshness_values else 0.0,
    }
    return {
        "snapshot_id": snapshot.snapshot_id,
        "workspace_id": snapshot.workspace_id,
        "universe_id": snapshot.universe_id,
        "as_of_time": snapshot.as_of_time.isoformat(),
        "created_at": snapshot.published_at.isoformat(),
        "nodes": wire_nodes,
        "relationships": relationships,
        "states": states,
        "coverage": coverage,
    }


def _display_endpoints(
    node_id: str,
    nodes: dict[str, Any],
    entity_to_instruments: dict[str, list[str]],
) -> list[str]:
    node = nodes[node_id]
    if node.kind == "entity":
        return entity_to_instruments.get(node_id, [])
    return [node_id]


def _edge_freshness(attributes: dict[str, Any], as_of_time: datetime) -> float:
    supported_at = attributes.get("last_supported_at")
    if not isinstance(supported_at, str):
        return 0.0
    try:
        timestamp = datetime.fromisoformat(supported_at)
    except ValueError:
        return 0.0
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return 0.0
    age_days = max(0.0, (as_of_time - timestamp).total_seconds() / 86_400)
    return exp(-log(2) * age_days / 180)


def _wire_diff(
    diff: Any, prior: TemporalGraphSnapshot, current: TemporalGraphSnapshot
) -> dict[str, Any]:
    old_nodes = {node.node_id: node for node in prior.nodes}
    new_nodes = {node.node_id: node for node in current.nodes}
    old_edges = {edge.edge_id: edge for edge in prior.edge_states}
    new_edges = {edge.edge_id: edge for edge in current.edge_states}

    def row(kind: str, item_id: str, label: str) -> dict[str, str]:
        return {"kind": kind, "id": item_id, "label": label}

    def records(
        node_ids: tuple[str, ...],
        edge_ids: tuple[str, ...],
        table: dict[str, Any],
        node_map: dict[str, Any],
    ) -> list[dict[str, str]]:
        output = [
            row("node", item_id, node_map[item_id].label)
            for item_id in node_ids
            if item_id in node_map
        ]
        output.extend(
            row(
                "relationship",
                item_id,
                f"{table[item_id].source_node_id} → {table[item_id].target_node_id}",
            )
            for item_id in edge_ids
            if item_id in table
        )
        return output

    return {
        "added": records(diff.added_node_ids, diff.added_edge_ids, new_edges, new_nodes),
        "removed": records(diff.removed_node_ids, diff.removed_edge_ids, old_edges, old_nodes),
        "changed": records(diff.changed_node_ids, diff.changed_edge_ids, new_edges, new_nodes),
    }
