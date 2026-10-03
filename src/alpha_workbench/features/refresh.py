"""Trusted graph-only workspace feature refresh through the durable job runner."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from alpha_workbench.features.builders import build_feature_frame, default_feature_catalog
from alpha_workbench.jobs.dispatch import Handler
from alpha_workbench.temporal_graph import GraphSnapshotNotFoundError

from .contracts import FeatureSetVersion
from .repository import FeatureRepository
from .workspace_bindings import WorkspaceFeatureBinding, WorkspaceFeatureBindingRepository


def refresh_workspace_features(
    workspace_repository: Any,
    graph_repository: Any,
    feature_repository: FeatureRepository,
    binding_repository: WorkspaceFeatureBindingRepository,
    *,
    workspace_id: str,
    as_of_time: datetime | None = None,
    knowledge_time: datetime | None = None,
    effective_time: datetime | None = None,
    expected_graph_snapshot_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, int, int]:
    """Build and persist a deterministic frame from a workspace's pinned graph."""

    clock = now or datetime.now(UTC)
    workspace = workspace_repository.latest_workspace(workspace_id)
    if not workspace.universe_id:
        raise ValueError("workspace has no locked universe")
    if not workspace.graph_version_id:
        raise ValueError("workspace has no pinned graph snapshot")
    if expected_graph_snapshot_id and workspace.graph_version_id != expected_graph_snapshot_id:
        raise ValueError("workspace graph pin changed after feature refresh submission")
    universe = workspace_repository.get_universe(workspace.universe_id)
    if universe.workspace_id != workspace_id:
        raise ValueError("locked universe belongs to a different workspace")
    try:
        graph = graph_repository.get(workspace.graph_version_id)
    except GraphSnapshotNotFoundError as error:
        raise ValueError("workspace pinned graph snapshot was not found") from error
    if graph.workspace_id != workspace_id or graph.universe_id != workspace.universe_id:
        raise ValueError("graph snapshot does not match workspace and locked universe")
    if graph.published_at > clock:
        raise ValueError("pinned graph snapshot was published in the future")

    effective_cutoff = effective_time or graph.as_of_time
    cutoff = as_of_time or max(graph.as_of_time, graph.published_at)
    knowledge_cutoff = knowledge_time or graph.knowledge_time
    for label, value in (("as_of_time", cutoff), ("knowledge_time", knowledge_cutoff)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must include a timezone offset")
        if value > clock:
            raise ValueError(f"{label} cannot be in the future")
    if cutoff > max(graph.as_of_time, graph.published_at):
        raise ValueError("requested cutoff exceeds the pinned graph snapshot")
    if knowledge_cutoff > graph.knowledge_time:
        raise ValueError("knowledge_time exceeds the pinned graph snapshot")
    if effective_cutoff != graph.as_of_time:
        raise ValueError("effective_time must match the pinned graph snapshot")
    if knowledge_cutoff > cutoff:
        raise ValueError("knowledge_time cannot be after the decision as_of_time")
    definitions = default_feature_catalog()
    for definition in definitions:
        feature_repository.put_definition(definition)

    identity = "|".join(
        (
            workspace_id,
            graph.snapshot_id,
            graph.content_sha256(),
            cutoff.astimezone(UTC).isoformat(),
            effective_cutoff.astimezone(UTC).isoformat(),
            knowledge_cutoff.astimezone(UTC).isoformat(),
        )
    )
    feature_set_id = "workspace-feature-set-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    feature_set = FeatureSetVersion(
        feature_set_id=feature_set_id,
        feature_definition_refs=tuple(f"{item.feature_id}:v{item.version}" for item in definitions),
        graph_snapshot_id=graph.snapshot_id,
        graph_snapshot_digest=graph.content_sha256(),
        created_at=cutoff,
    )
    feature_repository.put_feature_set(feature_set)
    manifest = build_feature_frame(
        feature_set,
        definitions,
        input_frames={},
        as_of_time=cutoff,
        knowledge_time=knowledge_cutoff,
        effective_time=effective_cutoff,
        graph_snapshot=graph,
    )
    for observation in manifest.feature_observations:
        feature_repository.put_observation(observation)
    feature_repository.put_manifest(manifest)

    prior_bindings = binding_repository.list_bindings(workspace_id)
    by_feature: dict[str, WorkspaceFeatureBinding] = {}
    for prior in prior_bindings:
        current = by_feature.get(prior.feature_id)
        if current is None or prior.version > current.version:
            by_feature[prior.feature_id] = prior
    readiness = {item.feature_id: item for item in manifest.readiness}
    observations: dict[str, list[Any]] = {}
    for observation in manifest.feature_observations:
        observations.setdefault(observation.feature_id, []).append(observation)

    ready_count = 0
    for definition in definitions:
        result = readiness[definition.feature_id]
        feature_observations = observations.get(definition.feature_id, [])
        available_at = max((item.available_at for item in feature_observations), default=None)
        proposed = WorkspaceFeatureBinding(
            workspace_id=workspace_id,
            feature_id=definition.feature_id,
            feature_version=definition.version,
            status=result.status,
            reason=result.reason,
            observation_count=result.observation_count,
            graph_snapshot_id=graph.snapshot_id if definition.required_graph else None,
            graph_snapshot_digest=graph.content_sha256() if definition.required_graph else None,
            available_at=available_at,
            source_artifact_ids=(manifest.manifest_id,),
            created_at=cutoff,
        )
        previous = by_feature.get(definition.feature_id)
        if previous is not None:
            if _binding_semantics(proposed) == _binding_semantics(previous):
                continue
            proposed = proposed.model_copy(update={"version": previous.version + 1})
        binding_repository.put_binding(proposed)
        ready_count += result.status == "ready"
    return manifest.manifest_id, len(manifest.feature_observations), ready_count


def _binding_semantics(binding: WorkspaceFeatureBinding) -> dict[str, Any]:
    payload = binding.model_dump(mode="json")
    payload.pop("version")
    payload.pop("created_at")
    return payload


def feature_refresh_handler(
    workspace_repository: Any,
    graph_repository: Any,
    feature_repository: FeatureRepository,
    binding_repository: WorkspaceFeatureBindingRepository,
) -> Handler:
    """Create a restart-safe feature refresh job handler."""

    def run(context: Any) -> None:
        workspace_id = str(context.payload.get("workspace_id", ""))
        if not workspace_id:
            raise ValueError("feature-refresh requires workspace_id")
        context.progress(
            0.1,
            "Validating locked workspace and graph",
            event_key=f"{context.job_id}:validate",
        )
        manifest_id, observation_count, ready_count = refresh_workspace_features(
            workspace_repository,
            graph_repository,
            feature_repository,
            binding_repository,
            workspace_id=workspace_id,
            as_of_time=_payload_time(context.payload, "as_of_time"),
            knowledge_time=_payload_time(context.payload, "knowledge_time"),
            effective_time=_payload_time(context.payload, "effective_time"),
            expected_graph_snapshot_id=str(context.payload.get("graph_snapshot_id", "")) or None,
        )
        context.progress(
            0.9,
            f"Persisted manifest {manifest_id}; {ready_count} features ready from "
            f"{observation_count} observations",
            event_key=f"{context.job_id}:persisted",
        )

    return run


def _payload_time(payload: Any, key: str) -> datetime | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"feature-refresh {key} must be a timestamp string")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ValueError(f"feature-refresh has invalid {key}") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"feature-refresh {key} must be timezone-aware")
    return value.astimezone(UTC)
