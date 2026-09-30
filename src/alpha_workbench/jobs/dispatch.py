"""Queue adapters and worker-facing cancellation/progress context."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import JobEvent, JobEventType, JobReceipt, JobRequest, JobStatus
from .protocols import JobRepository


class QueueClient(Protocol):
    def lpush(self, key: str, value: str) -> Any: ...

    def blpop(self, key: str, timeout: int = 0) -> Any: ...

    def brpoplpush(self, source: str, destination: str, timeout: int = 0) -> Any: ...

    def rpoplpush(self, source: str, destination: str) -> Any: ...

    def lrem(self, key: str, count: int, value: str | bytes) -> Any: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class QueueMessage:
    job_id: str
    kind: str
    payload: Mapping[str, Any]

    def encode(self) -> str:
        return json.dumps(
            {"job_id": self.job_id, "kind": self.kind, "payload": dict(self.payload)},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def decode(cls, raw: str | bytes) -> QueueMessage:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return cls(job_id=str(value["job_id"]), kind=str(value["kind"]), payload=value["payload"])


class InMemoryQueue:
    """Minimal queue fake with Redis-compatible method names."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._processing: list[str] = []
        self._enqueue_markers: set[str] = set()

    def rpush(self, key: str, value: str) -> int:
        del key
        self._items.append(value)
        return len(self._items)

    def lpush(self, key: str, value: str) -> int:
        del key
        self._items.insert(0, value)
        return len(self._items)

    def blpop(self, key: str, timeout: int = 0) -> tuple[str, str] | None:
        del timeout
        if not self._items:
            return None
        return key, self._items.pop(0)

    def brpoplpush(
        self, source: str, destination: str, timeout: int = 0
    ) -> str | None:
        del source, destination, timeout
        if not self._items:
            return None
        value = self._items.pop()
        self._processing.insert(0, value)
        return value

    def rpoplpush(self, source: str, destination: str) -> str | None:
        del source, destination
        if not self._processing:
            return None
        value = self._processing.pop()
        self._items.insert(0, value)
        return value

    def lrem(self, key: str, count: int, value: str | bytes) -> int:
        del key, count
        expected = value.decode("utf-8") if isinstance(value, bytes) else value
        try:
            self._processing.remove(expected)
        except ValueError:
            return 0
        return 1

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        del script, numkeys
        marker, _queue_name, value = keys_and_args
        if marker in self._enqueue_markers:
            return 0
        self._enqueue_markers.add(marker)
        self._items.insert(0, value)
        return 1


class JobDispatcher:
    """Submit jobs exactly once and publish idempotent progress events."""

    def __init__(
        self, repository: JobRepository, queue: QueueClient, *, queue_name: str = "alpha:jobs"
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.queue_name = queue_name

    def submit(self, request: JobRequest) -> JobReceipt:
        receipt, created = self.repository.create_or_get(request)
        if created or receipt.status == JobStatus.QUEUED:
            # The marker and LPUSH happen in one Redis operation. If Redis was
            # unavailable after the database insert, an idempotent retry repairs
            # the dispatch without putting a second message on the queue.
            self.queue.eval(
                "if redis.call('SETNX', KEYS[1], '1') == 1 then "
                "redis.call('LPUSH', KEYS[2], ARGV[1]); return 1 end; return 0",
                2,
                f"{self.queue_name}:submitted:{receipt.id}",
                self.queue_name,
                QueueMessage(receipt.id, receipt.kind, request.payload).encode(),
            )
        return receipt

    def cancel(self, job_id: str) -> bool:
        return self.repository.request_cancel(job_id)

    def publish_progress(
        self,
        job_id: str,
        progress: float,
        message: str | None = None,
        *,
        event_key: str | None = None,
    ) -> JobReceipt:
        key = event_key or f"{job_id}:progress:{progress:.12f}:{message or ''}"
        self.repository.append_event(
            JobEvent(
                job_id=job_id,
                event_type=JobEventType.PROGRESS,
                event_key=key,
                progress=progress,
                message=message,
            )
        )
        return self.repository.update_progress(job_id, progress, message)


class CancellationToken:
    def __init__(self, repository: JobRepository, job_id: str) -> None:
        self._repository = repository
        self.job_id = job_id

    @property
    def cancelled(self) -> bool:
        return self._repository.is_cancel_requested(self.job_id)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            from .worker import JobCancelled

            raise JobCancelled(f"job {self.job_id} was cancelled")


@dataclass(slots=True)
class JobContext:
    job_id: str
    kind: str
    payload: Mapping[str, Any]
    dispatcher: JobDispatcher
    cancellation: CancellationToken

    def progress(
        self, value: float, message: str | None = None, *, event_key: str | None = None
    ) -> None:
        self.cancellation.raise_if_cancelled()
        self.dispatcher.publish_progress(self.job_id, value, message, event_key=event_key)

    def check_cancelled(self) -> None:
        self.cancellation.raise_if_cancelled()


Handler = Callable[[JobContext], Any]
