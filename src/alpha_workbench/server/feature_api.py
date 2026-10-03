"""Workspace feature refresh submission API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alpha_workbench.jobs.contracts import JobRequest
from alpha_workbench.jobs.dispatch import JobDispatcher
from alpha_workbench.persistence.repositories import ProductRepository, RepositoryNotFoundError
from alpha_workbench.temporal_graph import GraphSnapshotNotFoundError, TemporalGraphRepository


class FeatureRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)


@dataclass(slots=True)
class FeatureApiDependencies:
    workspace_repository: ProductRepository
    graph_repository: TemporalGraphRepository
    dispatcher: JobDispatcher


def create_feature_router(dependencies: FeatureApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.post("/api/workspaces/{workspace_id}/feature-refresh", status_code=202)
    def refresh_features(workspace_id: str, request: FeatureRefreshRequest) -> dict[str, Any]:
        try:
            workspace = dependencies.workspace_repository.latest_workspace(workspace_id)
        except (KeyError, RepositoryNotFoundError) as error:
            raise HTTPException(status_code=404, detail="workspace not found") from error
        if not workspace.universe_id:
            raise HTTPException(status_code=409, detail="workspace has no locked universe")
        if not workspace.graph_version_id:
            raise HTTPException(status_code=409, detail="workspace has no pinned graph snapshot")
        get_universe = getattr(dependencies.workspace_repository, "get_universe", None)
        if not callable(get_universe):
            raise HTTPException(status_code=501, detail="universe repository is unavailable")
        try:
            universe = get_universe(workspace.universe_id)
            graph = dependencies.graph_repository.get(workspace.graph_version_id)
        except (KeyError, RepositoryNotFoundError) as error:
            raise HTTPException(
                status_code=404, detail="locked workspace source not found"
            ) from error
        except GraphSnapshotNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="pinned graph snapshot not found"
            ) from error
        if universe.workspace_id != workspace_id:
            raise HTTPException(
                status_code=409, detail="locked universe belongs to another workspace"
            )
        if graph.workspace_id != workspace_id or graph.universe_id != universe.universe_id:
            raise HTTPException(
                status_code=409,
                detail="graph snapshot does not match workspace and locked universe",
            )
        now = datetime.now(UTC)
        if graph.published_at > now or graph.as_of_time > now or graph.knowledge_time > now:
            raise HTTPException(
                status_code=409,
                detail="pinned graph snapshot contains a future time cutoff",
            )
        decision_time = max(graph.as_of_time, graph.published_at)
        if graph.knowledge_time > decision_time:
            raise HTTPException(
                status_code=409,
                detail="graph knowledge cutoff is after its decision availability",
            )

        idempotency_key = f"feature-refresh:{workspace_id}:{request.idempotency_key}"
        payload = {
            "workspace_id": workspace_id,
            "graph_snapshot_id": graph.snapshot_id,
            "as_of_time": decision_time.isoformat(),
            "effective_time": graph.as_of_time.isoformat(),
            "knowledge_time": graph.knowledge_time.isoformat(),
        }
        try:
            receipt = dependencies.dispatcher.submit(
                JobRequest(
                    kind="feature-refresh",
                    idempotency_key=idempotency_key,
                    job_id=str(uuid4()),
                    payload=payload,
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key conflicts with another refresh",
            ) from error
        return receipt.to_dict()

    return router
