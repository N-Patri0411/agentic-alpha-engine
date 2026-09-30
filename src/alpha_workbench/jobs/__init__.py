"""Durable, cancellable local job execution primitives.

The job package deliberately depends on protocols rather than the application
database models.  A persistence implementation can therefore be swapped in
without changing dispatchers or worker handlers.
"""

from .contracts import (
    JobEvent,
    JobEventType,
    JobReceipt,
    JobRequest,
    JobStatus,
    canonical_json,
)
from .dispatch import CancellationToken, InMemoryQueue, JobContext, JobDispatcher
from .handlers import workspace_bootstrap_handler
from .health import DependencyHealth, probe, readiness
from .repository import InMemoryJobRepository, PostgresJobRepository
from .worker import JobCancelled, JobWorker

__all__ = [
    "CancellationToken",
    "InMemoryJobRepository",
    "InMemoryQueue",
    "JobCancelled",
    "JobContext",
    "JobDispatcher",
    "JobEvent",
    "JobEventType",
    "JobReceipt",
    "JobRequest",
    "JobStatus",
    "JobWorker",
    "PostgresJobRepository",
    "canonical_json",
    "DependencyHealth",
    "probe",
    "readiness",
    "workspace_bootstrap_handler",
]
