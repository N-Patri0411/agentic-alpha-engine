"""Minimal Redis worker entrypoint used by the local Compose stack."""

from __future__ import annotations

import os
import time
from typing import Any, cast

from ..features.refresh import feature_refresh_handler
from ..graph_pipeline import GraphInputProvider, graph_refresh_handler
from ..persistence.repositories import ProductRepository
from ..temporal_graph import TemporalGraphRepository
from .dispatch import Handler
from .handlers import workspace_bootstrap_handler


def worker_handlers(
    workspace_repository: ProductRepository,
    graph_repository: TemporalGraphRepository,
    graph_inputs: GraphInputProvider,
    feature_repository: Any,
    feature_bindings: Any,
) -> dict[str, Handler]:
    """Build the shared production worker handler registry."""

    return {
        "workspace-bootstrap": workspace_bootstrap_handler(workspace_repository),
        "graph-refresh": graph_refresh_handler(
            workspace_repository, graph_repository, graph_inputs
        ),
        "feature-refresh": feature_refresh_handler(
            workspace_repository,
            graph_repository,
            feature_repository,
            feature_bindings,
        ),
    }


def main() -> None:
    try:
        import psycopg
        import redis
    except ImportError as error:  # pragma: no cover - exercised in container
        raise SystemExit(f"worker dependency missing: {error}") from error

    from ..features import PostgresFeatureRepository, PostgresWorkspaceFeatureBindingRepository
    from ..graph_pipeline import default_graph_input_provider
    from ..persistence.repositories import PostgresProductRepository
    from ..temporal_graph import PostgresTemporalGraphRepository
    from .dispatch import JobDispatcher, QueueClient
    from .repository import PostgresJobRepository
    from .worker import JobWorker

    database_url = os.environ.get("DATABASE_URL", "postgresql://alpha:alpha@postgres:5432/alpha")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    queue_name = os.environ.get("ALPHA_JOB_QUEUE", "alpha:jobs")
    repository = PostgresJobRepository(lambda: psycopg.connect(database_url))
    # redis-py's overloads are wider than the small runtime protocol, while the
    # concrete methods used by JobDispatcher/JobWorker have matching semantics.
    queue = cast(QueueClient, redis.Redis.from_url(redis_url))
    dispatcher = JobDispatcher(repository, queue, queue_name=queue_name)
    workspace_repository = PostgresProductRepository(psycopg.connect(database_url))
    graph_repository = PostgresTemporalGraphRepository(psycopg.connect(database_url))
    feature_repository = PostgresFeatureRepository(psycopg.connect(database_url))
    feature_bindings = PostgresWorkspaceFeatureBindingRepository(
        psycopg.connect(database_url)
    )
    graph_inputs = default_graph_input_provider()
    worker = JobWorker(
        dispatcher,
        handlers=worker_handlers(
            workspace_repository,
            graph_repository,
            graph_inputs,
            feature_repository,
            feature_bindings,
        ),
    )
    worker.recover()
    while True:
        worker.run_once(timeout=5)
        time.sleep(0.05)


if __name__ == "__main__":
    main()
