"""Workspace-scoped alpha, feature, and immutable strategy API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from alpha_workbench.agents.alpha_generator import AlphaGeneratorService
from alpha_workbench.alpha.catalog import GeneratorFeatureRef
from alpha_workbench.alpha.dsl import (
    DSLValidationError,
    canonicalize_expression,
    parse_expression,
    validate_typed_expression,
)
from alpha_workbench.features import (
    FeatureDefinition,
    WorkspaceFeatureBinding,
    WorkspaceFeatureBindingRepository,
    default_feature_catalog,
)
from alpha_workbench.persistence.repositories import ProductRepository, RepositoryNotFoundError
from alpha_workbench.product.contracts import DomainWorkspace, StrategySpec, UniverseSpec
from alpha_workbench.temporal_graph import GraphSnapshotNotFoundError, TemporalGraphRepository


class AlphaCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=1000)
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=100)
    universe_id: str = Field(min_length=1)
    graph_snapshot_id: str = Field(min_length=1)
    portfolio: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    experiment_id: str | None = None
    trial_limit: int = Field(default=100, ge=1, le=100_000)


class StrategyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str | None = None
    workspace_id: str | None = None
    name: str = Field(min_length=1, max_length=100)
    expression: str = Field(min_length=1, max_length=300)
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=100)
    universe_id: str = Field(min_length=1)
    graph_snapshot_id: str = Field(min_length=1)
    portfolio: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class AlphaApiDependencies:
    workspace_repository: ProductRepository
    feature_bindings: WorkspaceFeatureBindingRepository
    graph_repository: TemporalGraphRepository
    generator: AlphaGeneratorService


def create_alpha_router(dependencies: AlphaApiDependencies) -> APIRouter:
    router = APIRouter()
    definitions = default_feature_catalog()

    @router.get("/api/workspaces/{workspace_id}/features")
    def list_features(workspace_id: str) -> dict[str, Any]:
        workspace = _workspace(dependencies, workspace_id)
        bindings = dependencies.feature_bindings.list_bindings(workspace_id)
        by_feature: dict[str, list[Any]] = {}
        for feature_binding in bindings:
            by_feature.setdefault(feature_binding.feature_id, []).append(feature_binding)
        items = []
        for definition in definitions:
            binding: WorkspaceFeatureBinding | None = next(
                (
                    item
                    for item in reversed(by_feature.get(definition.feature_id, ()))
                    if item.feature_version == definition.version
                ),
                None,
            )
            as_of = datetime.now(UTC)
            if workspace.graph_version_id:
                try:
                    graph = dependencies.graph_repository.get(workspace.graph_version_id)
                    as_of = max(graph.as_of_time, graph.published_at)
                except GraphSnapshotNotFoundError:
                    binding = None
            ready = bool(
                binding
                and binding.ready_for(
                    as_of_time=as_of,
                    graph_snapshot_id=workspace.graph_version_id,
                )
            )
            if ready and binding is not None and definition.required_graph:
                try:
                    graph = dependencies.graph_repository.get(workspace.graph_version_id or "")
                    ready = binding.graph_snapshot_digest == graph.content_sha256()
                except GraphSnapshotNotFoundError:
                    ready = False
            items.append(
                {
                    "feature_id": definition.feature_id,
                    "name": definition.feature_id,
                    "version": definition.version,
                    "binding_version": binding.version if binding else None,
                    "category": _category(definition),
                    "description": definition.description,
                    "frequency": definition.frequency,
                    "available": ready,
                    "readiness": "ready" if ready else "unavailable",
                    "reason": (
                        None
                        if ready
                        else binding.reason
                        if binding and binding.reason
                        else "No ready feature binding exists for this workspace."
                    ),
                    "provenance": list(binding.source_artifact_ids) if binding else [],
                    "feature_version_id": f"{definition.feature_id}@v{definition.version}",
                    "dataset_version_id": binding.dataset_version_id if binding else None,
                    "graph_snapshot_id": binding.graph_snapshot_id if binding else None,
                    "graph_snapshot_digest": binding.graph_snapshot_digest if binding else None,
                    "available_at": binding.available_at.isoformat()
                    if binding and binding.available_at
                    else None,
                    "workspace_id": workspace_id,
                }
            )
        return {"workspace_id": workspace_id, "features": items}

    @router.post("/api/workspaces/{workspace_id}/alpha-candidates")
    def generate_candidates(workspace_id: str, request: AlphaCandidateRequest) -> dict[str, Any]:
        workspace, universe, graph, refs = _pinned_context(
            dependencies,
            workspace_id,
            request.universe_id,
            request.graph_snapshot_id,
            request.feature_names,
        )
        as_of = max(graph.as_of_time, graph.published_at)
        payload = {
            "features": refs,
            "context": request.intent,
            "frequency": workspace.cadence,
            "as_of_time": as_of,
            "graph_version_id": graph.snapshot_id,
            "portfolio_config": request.portfolio,
            "risk_config": request.risk,
        }
        experiment_id = request.experiment_id or f"{workspace_id}:alpha"
        try:
            result = dependencies.generator.generate(
                payload,
                run_id=str(uuid4()),
                experiment_id=experiment_id,
                trial_limit=request.trial_limit,
            )
        except Exception as error:
            # Provider error strings can contain request material or credentials.
            raise HTTPException(
                status_code=502, detail="alpha candidate generation failed"
            ) from error
        return {
            "workspace_id": workspace_id,
            "universe_id": universe.universe_id,
            "graph_snapshot_id": graph.snapshot_id,
            "candidates": [
                {
                    "candidate_id": candidate.id,
                    "id": candidate.id,
                    "name": candidate.rationale[:100],
                    "expression": candidate.signal.canonical_expression
                    if candidate.signal
                    else candidate.expression,
                    "rationale": candidate.rationale,
                    "feature_names": candidate.provenance.feature_names,
                    "status": "proposed",
                }
                for candidate in result.candidates
            ],
            "rejected": result.rejected,
            "experiment_id": result.experiment_id,
            "trial_count": result.trial_count,
            "trial_limit": result.trial_limit,
        }

    @router.get("/api/workspaces/{workspace_id}/strategies")
    def list_strategies(workspace_id: str) -> dict[str, Any]:
        _workspace(dependencies, workspace_id)
        listing = getattr(dependencies.workspace_repository, "list_strategies", None)
        if not callable(listing):
            raise HTTPException(status_code=501, detail="strategy listing is unavailable")
        return {"strategies": [_strategy_wire(item) for item in listing(workspace_id)]}

    @router.post("/api/workspaces/{workspace_id}/strategies", status_code=201)
    def save_strategy(workspace_id: str, request: StrategyRequest) -> dict[str, Any]:
        if request.workspace_id and request.workspace_id != workspace_id:
            raise HTTPException(status_code=409, detail="workspace does not match request path")
        strategy = _strategy_from_request(dependencies, workspace_id, request)
        try:
            stored = cast(StrategySpec, dependencies.workspace_repository.put(strategy))  # type: ignore[arg-type]
        except ValueError as error:
            raise HTTPException(status_code=409, detail="strategy version is immutable") from error
        return _strategy_wire(stored)

    @router.get("/api/strategies/{strategy_id}/versions")
    def strategy_versions(strategy_id: str) -> dict[str, Any]:
        versions = getattr(dependencies.workspace_repository, "list_versions", None)
        if not callable(versions):
            raise HTTPException(status_code=501, detail="strategy history is unavailable")
        try:
            records = versions(StrategySpec, strategy_id)
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404, detail="strategy not found") from error
        if not records:
            raise HTTPException(status_code=404, detail="strategy not found")
        return {"versions": [_strategy_wire(item) for item in records]}

    @router.post("/api/strategies/validate")
    def validate_strategy(request: StrategyRequest) -> dict[str, Any]:
        if not request.workspace_id:
            raise HTTPException(status_code=422, detail="workspace_id is required")
        _strategy_from_request(dependencies, request.workspace_id, request)
        return {
            "valid": True,
            "status": "passed",
            "message": (
                "DSL, workspace, universe, graph, and feature pins passed "
                "deterministic contract checks."
            ),
            "checks": [
                {"name": name, "status": "pass", "message": message}
                for name, message in (
                    ("dsl", "Expression uses registered typed DSL functions."),
                    ("workspace", "Workspace context exists."),
                    ("universe", "Locked universe matches workspace."),
                    ("graph", "Graph snapshot matches workspace and universe."),
                    ("feature_pins", "Selected features are ready and point-in-time available."),
                )
            ],
            "backtest_performed": False,
        }

    return router


def _strategy_from_request(
    dependencies: AlphaApiDependencies, workspace_id: str, request: StrategyRequest
) -> StrategySpec:
    workspace, universe, graph, refs = _pinned_context(
        dependencies,
        workspace_id,
        request.universe_id,
        request.graph_snapshot_id,
        request.feature_names,
    )
    try:
        parsed = parse_expression(request.expression, {item.name for item in refs})
        validate_typed_expression(
            parsed,
            supported_axes={item.name: ("cross_section", "time_series") for item in refs},
            frequency=workspace.cadence,
        )
        canonical = canonicalize_expression(request.expression, {item.name for item in refs})
    except (ValueError, DSLValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    strategy_id = request.strategy_id or str(uuid4())
    versions = getattr(dependencies.workspace_repository, "list_versions", None)
    current = versions(StrategySpec, strategy_id) if callable(versions) else ()
    if current and current[0].workspace_id != workspace_id:
        raise HTTPException(status_code=409, detail="strategy belongs to another workspace")
    return StrategySpec(
        strategy_id=strategy_id,
        version=max((item.version for item in current), default=0) + 1,
        workspace_id=workspace_id,
        universe_id=universe.universe_id,
        name=request.name,
        cadence=workspace.cadence,
        signal_expression=canonical,
        feature_names=tuple(item.name for item in refs),
        feature_version_ids=tuple(sorted(item.feature_version_id or "" for item in refs)),
        dataset_version_ids=tuple(
            sorted({item.dataset_version_id for item in refs if item.dataset_version_id})
        ),
        graph_version_id=graph.snapshot_id,
        portfolio_config=request.portfolio,
        risk_config=request.risk,
        status="draft",
    )


def _pinned_context(
    dependencies: AlphaApiDependencies,
    workspace_id: str,
    universe_id: str,
    graph_snapshot_id: str,
    feature_names: tuple[str, ...],
) -> tuple[DomainWorkspace, UniverseSpec, Any, list[GeneratorFeatureRef]]:
    workspace = _workspace(dependencies, workspace_id)
    if not workspace.universe_id or workspace.universe_id != universe_id:
        raise HTTPException(
            status_code=409, detail="universe does not match the locked workspace universe"
        )
    get_universe = getattr(dependencies.workspace_repository, "get_universe", None)
    if not callable(get_universe):
        raise HTTPException(status_code=501, detail="universe repository is unavailable")
    try:
        universe = get_universe(universe_id)
    except (KeyError, RepositoryNotFoundError) as error:
        raise HTTPException(status_code=404, detail="locked universe not found") from error
    if universe.workspace_id != workspace_id:
        raise HTTPException(status_code=409, detail="universe belongs to another workspace")
    try:
        graph = dependencies.graph_repository.get(graph_snapshot_id)
    except GraphSnapshotNotFoundError as error:
        raise HTTPException(status_code=404, detail="graph snapshot not found") from error
    if graph.workspace_id != workspace_id or graph.universe_id != universe_id:
        raise HTTPException(
            status_code=409, detail="graph snapshot does not match workspace and locked universe"
        )
    definitions = {item.feature_id: item for item in default_feature_catalog()}
    bindings = dependencies.feature_bindings.list_bindings(workspace_id)
    refs = []
    for name in feature_names:
        definition = definitions.get(name)
        if definition is None:
            raise HTTPException(status_code=422, detail=f"unknown feature {name!r}")
        binding = next(
            (
                item
                for item in reversed(bindings)
                if item.feature_id == name and item.feature_version == definition.version
            ),
            None,
        )
        if binding is None:
            raise HTTPException(
                status_code=422, detail=f"feature {name!r} has no workspace binding"
            )
        as_of = max(graph.as_of_time, graph.published_at)
        if not binding.ready_for(as_of_time=as_of, graph_snapshot_id=graph.snapshot_id):
            raise HTTPException(
                status_code=422,
                detail=f"feature {name!r} is unavailable at the selected graph as-of time",
            )
        if definition.required_graph and binding.graph_snapshot_digest != graph.content_sha256():
            raise HTTPException(
                status_code=409,
                detail=f"feature {name!r} graph provenance does not match the selected snapshot",
            )
        if not definition.required_graph and not binding.dataset_version_id:
            raise HTTPException(
                status_code=422,
                detail=f"feature {name!r} has no pinned dataset version",
            )
        refs.append(
            GeneratorFeatureRef(
                name=name,
                description=definition.description,
                frequency=definition.frequency if definition.frequency != "event" else "daily",
                feature_version_id=(
                    f"{definition.feature_id}@schema{binding.feature_version}:"
                    f"binding{binding.version}"
                ),
                dataset_version_id=binding.dataset_version_id,
                graph_version_id=binding.graph_snapshot_id,
                available_at=binding.available_at,
                source_artifact_ids=list(binding.source_artifact_ids),
            )
        )
    if len(set(feature_names)) != len(feature_names):
        raise HTTPException(status_code=422, detail="feature_names must be unique")
    return workspace, universe, graph, refs


def _workspace(dependencies: AlphaApiDependencies, workspace_id: str) -> DomainWorkspace:
    try:
        return dependencies.workspace_repository.latest_workspace(workspace_id)
    except RepositoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="workspace not found") from error


def _strategy_wire(strategy: StrategySpec) -> dict[str, Any]:
    payload = strategy.model_dump(mode="json")
    payload["expression"] = strategy.signal_expression
    return payload


def _category(definition: FeatureDefinition) -> str:
    return definition.family.replace("_", " ").title()
