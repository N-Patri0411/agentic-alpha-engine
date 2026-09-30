"""Restart-safe queue worker for local jobs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import JobEvent, JobEventType, JobStatus
from .dispatch import CancellationToken, JobContext, JobDispatcher, QueueMessage


class JobCancelled(Exception):
    """Raised by a handler when cancellation is observed."""


class JobWorker:
    def __init__(self, dispatcher: JobDispatcher, handlers: Mapping[str, Any]) -> None:
        self.dispatcher = dispatcher
        self.handlers = handlers

    def recover(self) -> list[str]:
        """Reclaim interrupted messages and requeue legacy orphaned running jobs."""

        reclaimed_ids: set[str] = set()
        while encoded := self.dispatcher.queue.rpoplpush(
            self.processing_queue_name, self.dispatcher.queue_name
        ):
            reclaimed_ids.add(QueueMessage.decode(encoded).job_id)
        receipts = self.dispatcher.repository.recover_incomplete()
        for receipt in receipts:
            if receipt.id in reclaimed_ids:
                continue
            payload_reader = getattr(self.dispatcher.repository, "payload", None)
            payload = payload_reader(receipt.id) if payload_reader else {}
            self.dispatcher.queue.lpush(
                self.dispatcher.queue_name,
                QueueMessage(receipt.id, receipt.kind, payload).encode(),
            )
        return [receipt.id for receipt in receipts]

    @property
    def processing_queue_name(self) -> str:
        return f"{self.dispatcher.queue_name}:processing"

    def run_once(self, *, timeout: int = 0) -> bool:
        encoded = self.dispatcher.queue.brpoplpush(
            self.dispatcher.queue_name,
            self.processing_queue_name,
            timeout=timeout,
        )
        if encoded is None:
            return False
        try:
            message = QueueMessage.decode(encoded)
            receipt = self.dispatcher.repository.get(message.job_id)
            if receipt is None:
                return True
            if receipt.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED}:
                return True
            if receipt.cancel_requested:
                self.dispatcher.repository.update_status(
                    receipt.id, JobStatus.CANCELED, message="cancelled before execution"
                )
                self.dispatcher.repository.append_event(
                    JobEvent(receipt.id, JobEventType.CANCELED, event_key=f"{receipt.id}:canceled")
                )
                return True
            handler = self.handlers.get(message.kind)
            if handler is None:
                self._fail(receipt.id, f"no handler registered for job kind {message.kind}")
                return True
            self.dispatcher.repository.update_status(
                receipt.id, JobStatus.RUNNING, message="started"
            )
            self.dispatcher.repository.append_event(
                JobEvent(receipt.id, JobEventType.STARTED, event_key=f"{receipt.id}:started")
            )
            context = JobContext(
                job_id=message.job_id,
                kind=message.kind,
                payload=message.payload,
                dispatcher=self.dispatcher,
                cancellation=CancellationToken(self.dispatcher.repository, message.job_id),
            )
            try:
                handler(context)
                context.cancellation.raise_if_cancelled()
            except JobCancelled as error:
                self.dispatcher.repository.update_status(
                    receipt.id, JobStatus.CANCELED, message=str(error)
                )
                self.dispatcher.repository.append_event(
                    JobEvent(receipt.id, JobEventType.CANCELED, event_key=f"{receipt.id}:canceled")
                )
            except Exception as error:  # worker must record failure and continue serving jobs
                self._fail(receipt.id, f"{type(error).__name__}: {error}")
            else:
                self.dispatcher.repository.update_status(
                    receipt.id, JobStatus.SUCCEEDED, message="completed"
                )
                self.dispatcher.repository.append_event(
                    JobEvent(
                        receipt.id,
                        JobEventType.COMPLETED,
                        event_key=f"{receipt.id}:completed",
                    )
                )
            return True
        finally:
            self.dispatcher.queue.lrem(self.processing_queue_name, 1, encoded)

    def _fail(self, job_id: str, message: str) -> None:
        self.dispatcher.repository.update_status(job_id, JobStatus.FAILED, message=message)
        self.dispatcher.repository.append_event(
            JobEvent(job_id, JobEventType.FAILED, event_key=f"{job_id}:failed", message=message)
        )
