"""Serializable contracts shared by the API, queue, and worker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def canonical_json(value: Any) -> str:
    """Return stable JSON for idempotency, manifests, and event payloads."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def payload_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "cancelled"
    CANCELLED = "cancelled"


class JobEventType(StrEnum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "cancelled"
    CANCELLED = "cancelled"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True)
class JobRequest:
    """A queue submission. ``idempotency_key`` is mandatory by design."""

    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str
    job_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("job kind must not be empty")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

    @property
    def payload_digest(self) -> str:
        return payload_digest(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
        }


@dataclass(frozen=True, slots=True)
class JobReceipt:
    id: str
    kind: str
    status: JobStatus
    idempotency_key: str
    payload_digest: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    message: str | None = None
    cancel_requested: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("job progress must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        """Serialize operational metadata only; payloads are never echoed."""

        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
            "created_at": _timestamp(self.created_at),
            "started_at": _timestamp(self.started_at),
            "finished_at": _timestamp(self.finished_at),
            "progress": self.progress,
            "message": self.message,
            "cancel_requested": self.cancel_requested,
        }


@dataclass(frozen=True, slots=True)
class JobEvent:
    job_id: str
    event_type: JobEventType
    event_key: str
    created_at: datetime = field(default_factory=utc_now)
    progress: float | None = None
    message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("event progress must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "event_type": self.event_type.value,
            "event_key": self.event_key,
            "created_at": _timestamp(self.created_at),
            "progress": self.progress,
            "message": self.message,
            "metadata": dict(self.metadata),
        }
