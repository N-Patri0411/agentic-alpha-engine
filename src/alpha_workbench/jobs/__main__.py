"""Minimal Redis worker entrypoint used by the local Compose stack."""

from __future__ import annotations

import os
import time
from typing import cast


def main() -> None:
    try:
        import psycopg
        import redis
    except ImportError as error:  # pragma: no cover - exercised in container
        raise SystemExit(f"worker dependency missing: {error}") from error

    from ..graph_pipeline import default_graph_input_provider, graph_refresh_handler
    from ..persistence.repositories import PostgresProductRepository
    from ..temporal_graph import PostgresTemporalGraphRepository
    from .dispatch import JobDispatcher, QueueClient
    from .handlers import workspace_bootstrap_handler
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
    graph_inputs = default_graph_input_provider()
    worker = JobWorker(
        dispatcher,
        handlers={
            "workspace-bootstrap": workspace_bootstrap_handler(workspace_repository),
            "graph-refresh": graph_refresh_handler(
                workspace_repository, graph_repository, graph_inputs
            ),
        },
    )
    worker.recover()
    while True:
        worker.run_once(timeout=5)
        time.sleep(0.05)


if __name__ == "__main__":
    main()
