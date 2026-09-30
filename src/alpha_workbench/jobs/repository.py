"""In-memory and PostgreSQL job receipt repositories.

The PostgreSQL implementation uses only a connection factory and standard
DB-API calls.  This keeps it compatible with the persistence agent's eventual
pool/session choice while making the runtime fully testable without a server.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .contracts import JobEvent, JobEventType, JobReceipt, JobRequest, JobStatus, utc_now

_TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class InMemoryJobRepository:
    """Thread-safe enough for a single local worker and deterministic tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobReceipt] = {}
        self._payloads: dict[str, dict[str, Any]] = {}
        self._by_key: dict[str, str] = {}
        self._events: dict[str, list[JobEvent]] = {}
        self._event_keys: set[str] = set()

    def create_or_get(self, request: JobRequest) -> tuple[JobReceipt, bool]:
        prior_id = self._by_key.get(request.idempotency_key)
        if prior_id is not None:
            prior = self._jobs[prior_id]
            if prior.payload_digest != request.payload_digest or prior.kind != request.kind:
                raise ValueError("idempotency key was already used with a different job")
            return prior, False
        now = utc_now()
        receipt = JobReceipt(
            id=request.job_id,
            kind=request.kind,
            status=JobStatus.QUEUED,
            idempotency_key=request.idempotency_key,
            payload_digest=request.payload_digest,
            created_at=now,
        )
        self._jobs[receipt.id] = receipt
        self._payloads[receipt.id] = dict(request.payload)
        self._by_key[request.idempotency_key] = receipt.id
        self._events[receipt.id] = []
        self.append_event(
            JobEvent(receipt.id, JobEventType.QUEUED, event_key=f"{receipt.id}:queued")
        )
        return receipt, True

    def payload(self, job_id: str) -> dict[str, Any]:
        return dict(self._payloads[job_id])

    def get(self, job_id: str) -> JobReceipt | None:
        return self._jobs.get(job_id)

    def find_by_idempotency(self, idempotency_key: str) -> JobReceipt | None:
        job_id = self._by_key.get(idempotency_key)
        return self._jobs.get(job_id) if job_id else None

    def list_jobs(self) -> list[JobReceipt]:
        return sorted(self._jobs.values(), key=lambda receipt: (receipt.created_at, receipt.id))

    def append_event(self, event: JobEvent) -> bool:
        if event.event_key in self._event_keys:
            return False
        if event.job_id not in self._jobs:
            raise KeyError(f"unknown job {event.job_id}")
        self._event_keys.add(event.event_key)
        self._events[event.job_id].append(event)
        return True

    def list_events(self, job_id: str) -> list[JobEvent]:
        return list(self._events.get(job_id, []))

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        progress: float | None = None,
        message: str | None = None,
        at: datetime | None = None,
    ) -> JobReceipt:
        current = self._jobs[job_id]
        if current.status in _TERMINAL and status != current.status:
            raise ValueError(f"terminal job cannot transition from {current.status} to {status}")
        timestamp = _ensure_utc(at or utc_now())
        started_at = current.started_at
        finished_at = current.finished_at
        if status == JobStatus.RUNNING and started_at is None:
            started_at = timestamp
        if status in _TERMINAL:
            finished_at = timestamp
        next_progress = current.progress if progress is None else progress
        if status == JobStatus.SUCCEEDED:
            next_progress = 1.0
        self._jobs[job_id] = replace(
            current,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            progress=next_progress,
            message=message,
        )
        return self._jobs[job_id]

    def update_progress(
        self, job_id: str, progress: float, message: str | None = None
    ) -> JobReceipt:
        current = self._jobs[job_id]
        if current.status != JobStatus.RUNNING:
            raise ValueError("progress can only be updated for a running job")
        return self.update_status(job_id, JobStatus.RUNNING, progress=progress, message=message)

    def request_cancel(self, job_id: str) -> bool:
        current = self._jobs.get(job_id)
        if current is None or current.status in _TERMINAL:
            return False
        self._jobs[job_id] = replace(current, cancel_requested=True)
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        receipt = self._jobs.get(job_id)
        return receipt.cancel_requested if receipt else False

    def recover_incomplete(self) -> list[JobReceipt]:
        recovered: list[JobReceipt] = []
        for job_id, receipt in list(self._jobs.items()):
            if receipt.status == JobStatus.RUNNING:
                recovered.append(
                    self.update_status(
                        job_id,
                        JobStatus.QUEUED,
                        message="worker restart recovery",
                    )
                )
                self.append_event(
                    JobEvent(job_id, JobEventType.RECOVERED, event_key=f"{job_id}:recovered")
                )
        return recovered


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    message TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS job_events (
    event_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    progress DOUBLE PRECISION,
    message TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS job_events_job_id_created_at_idx
    ON job_events(job_id, created_at);
"""


class PostgresJobRepository:
    """Durable repository backed by psycopg 3 through a connection factory."""

    def __init__(self, connection_factory: Callable[[], Any], *, initialize: bool = True) -> None:
        self._connection_factory = connection_factory
        if initialize:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(POSTGRES_SCHEMA)
            connection.commit()

    @staticmethod
    def _row_to_receipt(row: tuple[Any, ...]) -> JobReceipt:
        return JobReceipt(
            id=str(row[0]),
            kind=str(row[1]),
            status=JobStatus(str(row[2])),
            idempotency_key=str(row[3]),
            payload_digest=str(row[4]),
            created_at=_ensure_utc(row[5]),
            started_at=_ensure_utc(row[6]) if row[6] else None,
            finished_at=_ensure_utc(row[7]) if row[7] else None,
            progress=float(row[8]),
            message=row[9],
            cancel_requested=bool(row[10]),
        )

    def create_or_get(self, request: JobRequest) -> tuple[JobReceipt, bool]:
        query = """
        INSERT INTO jobs (id, kind, status, idempotency_key, payload_digest,
                          payload_json, created_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        """
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    query,
                    (
                        request.job_id,
                        request.kind,
                        JobStatus.QUEUED.value,
                        request.idempotency_key,
                        request.payload_digest,
                        json.dumps(dict(request.payload), sort_keys=True, separators=(",", ":")),
                        utc_now(),
                    ),
                )
                created = cursor.rowcount == 1
                cursor.execute(
                    "SELECT id, kind, status, idempotency_key, payload_digest, created_at, "
                    "started_at, finished_at, progress, message, cancel_requested "
                    "FROM jobs WHERE idempotency_key = %s",
                    (request.idempotency_key,),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("job insert did not return a receipt")
        receipt = self._row_to_receipt(row)
        if created:
            self.append_event(
                JobEvent(receipt.id, JobEventType.QUEUED, event_key=f"{receipt.id}:queued")
            )
        if receipt.kind != request.kind or receipt.payload_digest != request.payload_digest:
            raise ValueError("idempotency key was already used with a different job")
        return receipt, created

    def get(self, job_id: str) -> JobReceipt | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, kind, status, idempotency_key, payload_digest, created_at, "
                    "started_at, finished_at, progress, message, cancel_requested "
                    "FROM jobs WHERE id=%s",
                    (job_id,),
                )
                row = cursor.fetchone()
        return self._row_to_receipt(row) if row else None

    def payload(self, job_id: str) -> dict[str, Any]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload_json FROM jobs WHERE id=%s", (job_id,))
                row = cursor.fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row[0])

    def find_by_idempotency(self, idempotency_key: str) -> JobReceipt | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, kind, status, idempotency_key, payload_digest, created_at, "
                    "started_at, finished_at, progress, message, cancel_requested FROM jobs "
                    "WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
        return self._row_to_receipt(row) if row else None

    def list_jobs(self) -> list[JobReceipt]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, kind, status, idempotency_key, payload_digest, created_at, "
                    "started_at, finished_at, progress, message, cancel_requested "
                    "FROM jobs ORDER BY created_at, id"
                )
                rows = cursor.fetchall()
        return [self._row_to_receipt(row) for row in rows]

    def append_event(self, event: JobEvent) -> bool:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO job_events(event_key, job_id, event_type, created_at, "
                    "progress, message, metadata_json) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(event_key) DO NOTHING",
                    (
                        event.event_key,
                        event.job_id,
                        event.event_type.value,
                        event.created_at,
                        event.progress,
                        event.message,
                        json.dumps(dict(event.metadata), sort_keys=True, separators=(",", ":")),
                    ),
                )
                inserted = bool(cursor.rowcount == 1)
            connection.commit()
        return inserted

    def list_events(self, job_id: str) -> list[JobEvent]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT job_id,event_type,event_key,created_at,progress,message,metadata_json "
                    "FROM job_events WHERE job_id=%s ORDER BY created_at,event_key",
                    (job_id,),
                )
                rows = cursor.fetchall()
        return [
            JobEvent(
                job_id=str(row[0]),
                event_type=JobEventType(str(row[1])),
                event_key=str(row[2]),
                created_at=_ensure_utc(row[3]),
                progress=float(row[4]) if row[4] is not None else None,
                message=row[5],
                metadata=row[6] or {},
            )
            for row in rows
        ]

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        progress: float | None = None,
        message: str | None = None,
        at: datetime | None = None,
    ) -> JobReceipt:
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if current.status in _TERMINAL and status != current.status:
            raise ValueError(f"terminal job cannot transition from {current.status} to {status}")
        timestamp = _ensure_utc(at or utc_now())
        next_progress = current.progress if progress is None else progress
        if status == JobStatus.SUCCEEDED:
            next_progress = 1.0
        started_at = current.started_at or (timestamp if status == JobStatus.RUNNING else None)
        finished_at = timestamp if status in _TERMINAL else current.finished_at
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET status=%s, started_at=%s, finished_at=%s, "
                    "progress=%s, message=%s "
                    "WHERE id=%s",
                    (
                        status.value,
                        started_at,
                        finished_at,
                        next_progress,
                        message,
                        job_id,
                    ),
                )
            connection.commit()
        result = self.get(job_id)
        if result is None:
            raise RuntimeError("job disappeared while updating")
        return result

    def update_progress(
        self, job_id: str, progress: float, message: str | None = None
    ) -> JobReceipt:
        current = self.get(job_id)
        if current is None:
            raise KeyError(job_id)
        if current.status != JobStatus.RUNNING:
            raise ValueError("progress can only be updated for a running job")
        return self.update_status(job_id, JobStatus.RUNNING, progress=progress, message=message)

    def request_cancel(self, job_id: str) -> bool:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET cancel_requested=TRUE WHERE id=%s "
                    "AND status NOT IN (%s,%s,%s)",
                    (
                        job_id,
                        JobStatus.SUCCEEDED.value,
                        JobStatus.FAILED.value,
                        JobStatus.CANCELED.value,
                    ),
                )
                changed = bool(cursor.rowcount == 1)
            connection.commit()
        return changed

    def is_cancel_requested(self, job_id: str) -> bool:
        receipt = self.get(job_id)
        return receipt.cancel_requested if receipt else False

    def recover_incomplete(self) -> list[JobReceipt]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE jobs SET status=%s, message=%s WHERE status=%s RETURNING id",
                    (JobStatus.QUEUED.value, "worker restart recovery", JobStatus.RUNNING.value),
                )
                ids = [str(row[0]) for row in cursor.fetchall()]
            connection.commit()
        recovered: list[JobReceipt] = []
        for job_id in ids:
            self.append_event(
                JobEvent(job_id, JobEventType.RECOVERED, event_key=f"{job_id}:recovered")
            )
            receipt = self.get(job_id)
            if receipt:
                recovered.append(receipt)
        return recovered
