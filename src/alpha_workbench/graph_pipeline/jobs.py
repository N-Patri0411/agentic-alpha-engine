"""Offline job entry points for initial, nightly, and evidence-triggered graph work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from alpha_workbench.jobs.dispatch import Handler
from alpha_workbench.temporal_graph.repository import TemporalGraphRepository

from .contracts import GraphPipelineReport, GraphPipelineRequest
from .inputs import GraphInputProvider
from .service import bootstrap_graph, update_graph


def run_graph_pipeline_job(
    request: GraphPipelineRequest, repository: TemporalGraphRepository
) -> GraphPipelineReport:
    """Callable job handler; scheduling and queue dispatch remain external."""
    if request.trigger == "bootstrap":
        _, report = bootstrap_graph(request, repository)
        return report
    _, report = update_graph(request, repository)
    return report


def nightly_request(request: GraphPipelineRequest) -> GraphPipelineRequest:
    """Mark a prepared evidence batch as a scheduled full maintenance run."""
    return request.model_copy(update={"trigger": "nightly"})


def event_request(request: GraphPipelineRequest) -> GraphPipelineRequest:
    """Mark a prepared evidence batch as an affected-edge event update."""
    return request.model_copy(update={"trigger": "event"})


def graph_refresh_handler(
    workspace_repository: Any,
    graph_repository: TemporalGraphRepository,
    input_provider: GraphInputProvider,
) -> Handler:
    """Create a restart-safe queued refresh handler using only durable job inputs."""

    def run(context: Any) -> None:
        workspace_id = str(context.payload.get("workspace_id", ""))
        if not workspace_id:
            raise ValueError("graph-refresh requires workspace_id")
        workspace = workspace_repository.latest_workspace(workspace_id)
        if not workspace.universe_id:
            raise ValueError("workspace has no locked universe")
        trigger: Literal["bootstrap", "nightly"]
        try:
            universe = workspace_repository.get_universe(workspace.universe_id)
        except (AttributeError, KeyError) as error:
            raise ValueError("locked universe could not be loaded") from error
        if universe.workspace_id != workspace_id:
            raise ValueError("locked universe belongs to a different workspace")

        as_of_time = _job_time(context.payload, "as_of_time")
        knowledge_time = _job_time(context.payload, "knowledge_time")
        context.progress(0.15, "Locked universe loaded", event_key=f"{context.job_id}:universe")
        inputs = input_provider.load(universe, as_of_time=as_of_time, knowledge_time=knowledge_time)
        context.progress(
            0.45,
            f"Loaded {len(inputs.observations)} available evidence records",
            event_key=f"{context.job_id}:evidence",
        )
        try:
            graph_repository.latest(workspace_id)
            trigger = "nightly"
        except KeyError:
            trigger = "bootstrap"
        request = GraphPipelineRequest(
            universe=universe,
            as_of_time=as_of_time,
            knowledge_time=knowledge_time,
            observations=inputs.observations,
            validated_proposals=inputs.proposals,
            validation_reports=inputs.validation_reports,
            assessments=inputs.assessments,
            aliases=inputs.aliases or {},
            trigger=trigger,
            request_id=context.job_id,
        )
        snapshot, report = (
            bootstrap_graph(request, graph_repository)
            if trigger == "bootstrap"
            else update_graph(request, graph_repository)
        )
        eligible_edges = sum(
            edge.strategy_eligible == "eligible" and edge.lifecycle_status == "active"
            for edge in snapshot.visible_edge_states()
        )
        if not snapshot.edge_states:
            message = "Published node-only graph; no evidence-backed relationships were available."
        elif eligible_edges == 0:
            message = "Published graph with no strategy-eligible relationships."
        else:
            message = f"Published graph with {eligible_edges} strategy-eligible relationships."
        context.progress(0.9, message, event_key=f"{context.job_id}:published")
        if inputs.warnings:
            context.progress(
                0.95,
                "; ".join(inputs.warnings)[:500],
                event_key=f"{context.job_id}:warnings",
            )
        elif report.excluded_observation_ids:
            context.progress(
                0.95,
                f"Excluded {len(report.excluded_observation_ids)} future evidence records.",
                event_key=f"{context.job_id}:cutoff",
            )

    return run


def _job_time(payload: Any, key: str) -> datetime:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise ValueError(f"graph-refresh requires {key}")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"graph-refresh has invalid {key}") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"graph-refresh {key} must be timezone-aware")
    return value.astimezone(UTC)
