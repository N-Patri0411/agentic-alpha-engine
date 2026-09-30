"""Small protocols that allow the runtime to integrate with any persistence layer."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .contracts import JobEvent, JobReceipt, JobRequest, JobStatus


class JobRepository(Protocol):
    def create_or_get(self, request: JobRequest) -> tuple[JobReceipt, bool]: ...

    def get(self, job_id: str) -> JobReceipt | None: ...

    def find_by_idempotency(self, idempotency_key: str) -> JobReceipt | None: ...

    def list_jobs(self) -> list[JobReceipt]: ...

    def append_event(self, event: JobEvent) -> bool: ...

    def list_events(self, job_id: str) -> list[JobEvent]: ...

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        progress: float | None = None,
        message: str | None = None,
        at: datetime | None = None,
    ) -> JobReceipt: ...

    def update_progress(
        self, job_id: str, progress: float, message: str | None = None
    ) -> JobReceipt: ...

    def request_cancel(self, job_id: str) -> bool: ...

    def is_cancel_requested(self, job_id: str) -> bool: ...

    def recover_incomplete(self) -> list[JobReceipt]: ...
