"""Local FastAPI boundary for the Wave 1 production application."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..agents.alpha_generator import (
    AlphaGeneratorAgent,
    AlphaGeneratorService,
    InMemoryTrialLedger,
    PostgresTrialLedger,
)
from ..agents.contracts import AgentRun
from ..features import (
    InMemoryWorkspaceFeatureBindingRepository,
    PostgresWorkspaceFeatureBindingRepository,
)
from ..graph_pipeline import (
    EmptyGraphInputProvider,
    GraphInputProvider,
    TemporalGraphRepository,
    default_graph_input_provider,
    graph_refresh_handler,
)
from ..jobs.contracts import JobRequest as RuntimeJobRequest
from ..jobs.dispatch import InMemoryQueue, JobDispatcher, QueueClient
from ..jobs.handlers import workspace_bootstrap_handler
from ..jobs.health import probe
from ..jobs.health import readiness as evaluate_readiness
from ..jobs.protocols import JobRepository
from ..jobs.repository import InMemoryJobRepository, PostgresJobRepository
from ..jobs.worker import JobWorker
from ..llm.models import FakeLLMClient, create_llm, load_model_config
from ..persistence.repositories import (
    InMemoryVersionedRepository,
    PostgresProductRepository,
    ProductRepository,
    RepositoryNotFoundError,
)
from ..product import DomainWorkspace
from ..providers.registry import ProviderRegistry
from ..temporal_graph import InMemoryTemporalGraphRepository, PostgresTemporalGraphRepository
from .alpha_api import AlphaApiDependencies, create_alpha_router
from .domain_api import DomainApiDependencies, create_domain_router
from .graph_api import GraphApiDependencies, create_graph_router


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = None
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    cadence: Literal["daily", "weekly", "monthly"] = "daily"
    regions: tuple[str, ...] = ()
    universe_id: str | None = None
    graph_version_id: str | None = None
    status: Literal["draft", "building", "ready", "degraded", "archived"] = "draft"
    provider_ids: tuple[str, ...] = ()


class JobSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    job_id: str | None = None


@dataclass(slots=True)
class AppDependencies:
    workspace_repository: ProductRepository
    job_repository: JobRepository
    queue: QueueClient
    dispatcher: JobDispatcher
    graph_repository: TemporalGraphRepository
    graph_input_provider: GraphInputProvider
    feature_bindings: Any = field(default_factory=InMemoryWorkspaceFeatureBindingRepository)
    alpha_generator: AlphaGeneratorService = field(
        default_factory=lambda: AlphaGeneratorService(
            AlphaGeneratorAgent(FakeLLMClient({"candidates": []})), InMemoryTrialLedger()
        )
    )
    provider_registry: ProviderRegistry = field(default_factory=ProviderRegistry)
    worker: JobWorker | None = None
    readiness_probes: tuple[tuple[str, Callable[[], object]], ...] = field(default_factory=tuple)


def _workspace_payload(request: WorkspaceCreate) -> dict[str, Any]:
    values = request.model_dump()
    values["workspace_id"] = values["workspace_id"] or str(uuid4())
    return values


def make_in_memory_dependencies(
    provider_registry: ProviderRegistry | None = None,
    graph_input_provider: GraphInputProvider | None = None,
) -> AppDependencies:
    workspace_repository: ProductRepository = InMemoryVersionedRepository()
    job_repository = InMemoryJobRepository()
    queue = InMemoryQueue()
    dispatcher = JobDispatcher(job_repository, queue)
    graph_repository = InMemoryTemporalGraphRepository()
    input_provider = graph_input_provider or EmptyGraphInputProvider()
    dependencies = AppDependencies(
        workspace_repository=workspace_repository,
        job_repository=job_repository,
        queue=queue,
        dispatcher=dispatcher,
        graph_repository=graph_repository,
        graph_input_provider=input_provider,
        feature_bindings=InMemoryWorkspaceFeatureBindingRepository(),
        provider_registry=provider_registry or _provider_registry_from_environment(),
        readiness_probes=(
            ("workspace_store", lambda: True),
            ("job_dispatch", lambda: True),
        ),
    )
    dependencies.worker = JobWorker(
        dispatcher,
        {
            "workspace-bootstrap": workspace_bootstrap_handler(workspace_repository),
            "graph-refresh": graph_refresh_handler(
                workspace_repository, graph_repository, input_provider
            ),
        },
    )
    return dependencies


def make_environment_dependencies() -> AppDependencies:
    """Build Postgres/Redis only when both local URLs are explicitly configured."""

    database_url = os.environ.get("DATABASE_URL")
    redis_url = os.environ.get("REDIS_URL")
    if not database_url or not redis_url:
        return make_in_memory_dependencies()
    try:
        import psycopg
        import redis
    except ImportError as error:  # pragma: no cover - exercised in packaged runtime
        raise RuntimeError(
            "DATABASE_URL/REDIS_URL require psycopg and redis dependencies"
        ) from error

    def connection_factory() -> Any:
        return psycopg.connect(database_url)

    workspace_repository = PostgresProductRepository(connection_factory())
    job_repository = PostgresJobRepository(connection_factory)
    redis_client = redis.Redis.from_url(redis_url)
    queue = cast(QueueClient, redis_client)

    def postgres_ready() -> bool:
        with connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return bool(cursor.fetchone() == (1,))

    def redis_ready() -> bool:
        return bool(redis_client.ping())

    dispatcher = JobDispatcher(job_repository, queue)
    dependencies = AppDependencies(
        workspace_repository=workspace_repository,
        job_repository=job_repository,
        queue=queue,
        dispatcher=dispatcher,
        graph_repository=PostgresTemporalGraphRepository(connection_factory()),
        graph_input_provider=default_graph_input_provider(),
        feature_bindings=PostgresWorkspaceFeatureBindingRepository(connection_factory()),
        alpha_generator=AlphaGeneratorService(
            AlphaGeneratorAgent(
                create_llm(load_model_config(Path("config/models.yaml"), "alpha_generator"))
            ),
            PostgresTrialLedger(connection_factory),
        ),
        provider_registry=_provider_registry_from_environment(),
        readiness_probes=(("postgres", postgres_ready), ("redis", redis_ready)),
    )
    return dependencies


def create_app(dependencies: AppDependencies | None = None) -> FastAPI:
    dependencies = dependencies or make_environment_dependencies()
    app = FastAPI(title="Agentic Alpha Studio", version="0.1.0")
    app.include_router(
        create_domain_router(
            DomainApiDependencies(dependencies.provider_registry, dependencies.workspace_repository)
        )
    )
    app.include_router(
        create_graph_router(
            GraphApiDependencies(
                dependencies.workspace_repository,
                dependencies.graph_repository,
                dependencies.graph_input_provider,
                dependencies.dispatcher,
            )
        )
    )
    app.include_router(
        create_alpha_router(
            AlphaApiDependencies(
                dependencies.workspace_repository,
                dependencies.feature_bindings,
                dependencies.graph_repository,
                dependencies.alpha_generator,
            )
        )
    )
    runs: dict[str, AgentRun] = {}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "scope": "local-only",
        }

    @app.get("/api/readiness")
    def readiness(response: Response) -> dict[str, Any]:
        ready, checks = evaluate_readiness(
            probe(name, check) for name, check in dependencies.readiness_probes
        )
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        public_checks = [
            {
                "name": check.name,
                "status": "pass" if check.ok else "fail",
                "detail": check.detail,
            }
            for check in checks
        ]
        return {"status": "ready" if ready else "degraded", "checks": public_checks}

    @app.post("/api/workspaces", status_code=status.HTTP_201_CREATED)
    def create_workspace(request: WorkspaceCreate) -> DomainWorkspace:
        workspace = DomainWorkspace(**_workspace_payload(request))
        try:
            stored = dependencies.workspace_repository.put(workspace)
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="workspace version already exists"
            ) from error
        return stored

    @app.get("/api/workspaces")
    def list_workspaces() -> list[DomainWorkspace]:
        return list(dependencies.workspace_repository.list_workspaces(latest_only=True))

    @app.get("/api/workspaces/{workspace_id}")
    def get_workspace(workspace_id: str) -> DomainWorkspace:
        try:
            return dependencies.workspace_repository.latest_workspace(workspace_id)
        except RepositoryNotFoundError as error:
            raise HTTPException(status_code=404, detail="workspace not found") from error

    @app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED)
    def submit_job(request: JobSubmit) -> dict[str, Any]:
        job_request = RuntimeJobRequest(
            kind=request.kind,
            payload=request.payload,
            idempotency_key=request.idempotency_key,
            job_id=request.job_id or str(uuid4()),
        )
        try:
            receipt = dependencies.dispatcher.submit(job_request)
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail="idempotency key conflicts with another job",
            ) from error
        if request.kind == "workspace-bootstrap":
            if dependencies.worker is not None:
                dependencies.worker.run_once()
        return receipt.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [receipt.to_dict() for receipt in dependencies.job_repository.list_jobs()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        receipt = dependencies.job_repository.get(job_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="job not found")
        return receipt.to_dict()

    @app.get("/api/jobs/{job_id}/events")
    def list_job_events(job_id: str) -> list[dict[str, Any]]:
        if dependencies.job_repository.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        return [event.to_dict() for event in dependencies.job_repository.list_events(job_id)]

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        receipt = dependencies.job_repository.get(job_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="job not found")
        dependencies.dispatcher.cancel(job_id)
        updated = dependencies.job_repository.get(job_id)
        return updated.to_dict() if updated else receipt.to_dict()

    @app.post("/api/runs", status_code=201)
    def start_run(request: StartRunRequest) -> AgentRun:
        del request
        run = AgentRun(id=str(uuid4()), created_at=datetime.now(UTC))
        runs[run.id] = run
        return run

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> AgentRun:
        try:
            return runs[run_id]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.get("/api/proposals")
    def list_proposals() -> list[object]:
        return []

    return app


def _provider_registry_from_environment() -> ProviderRegistry:
    """Build only adapters with credentials available in the process environment."""

    try:
        return ProviderRegistry.from_config()
    except (OSError, ValueError):  # pragma: no cover - packaged config always exists
        return ProviderRegistry()


class StartRunRequest(BaseModel):
    name: str


_legacy_runs: dict[str, AgentRun] = {}


def health() -> dict[str, Any]:
    """Compatibility function retained for callers predating the app factory."""

    return {
        "status": "ok",
        "scope": "local-only",
    }


def start_run(request: StartRunRequest) -> AgentRun:
    """Create a legacy in-process run outside the FastAPI dependency graph."""

    del request
    run = AgentRun(id=str(uuid4()), created_at=datetime.now(UTC))
    _legacy_runs[run.id] = run
    return run


def get_run(run_id: str) -> AgentRun:
    """Read a run created through the legacy direct-call interface."""

    try:
        return _legacy_runs[run_id]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="run not found") from error


app = create_app()
