from alpha_workbench.jobs.contracts import (
    JobEvent,
    JobEventType,
    JobRequest,
    JobStatus,
    canonical_json,
)
from alpha_workbench.jobs.dispatch import InMemoryQueue, JobDispatcher
from alpha_workbench.jobs.health import DependencyHealth, probe, readiness
from alpha_workbench.jobs.repository import InMemoryJobRepository
from alpha_workbench.jobs.worker import JobCancelled, JobWorker


def _runtime() -> tuple[InMemoryJobRepository, JobDispatcher, InMemoryQueue]:
    repository = InMemoryJobRepository()
    queue = InMemoryQueue()
    return repository, JobDispatcher(repository, queue), queue


def test_submit_is_idempotent_and_progress_events_are_deduplicated() -> None:
    repository, dispatcher, queue = _runtime()
    first = dispatcher.submit(JobRequest("demo", {"value": 1}, "same-request"))
    second = dispatcher.submit(JobRequest("demo", {"value": 1}, "same-request"))
    assert first.id == second.id
    assert len(queue._items) == 1  # noqa: SLF001 - intentionally inspect the fake queue

    repository.update_status(first.id, JobStatus.RUNNING)
    dispatcher.publish_progress(first.id, 0.5, "halfway", event_key="step-1")
    dispatcher.publish_progress(first.id, 0.5, "halfway", event_key="step-1")
    progress_events = [
        event
        for event in repository.list_events(first.id)
        if event.event_type == JobEventType.PROGRESS
    ]
    assert len(progress_events) == 1


def test_retry_repairs_dispatch_after_redis_was_temporarily_unavailable() -> None:
    repository, dispatcher, queue = _runtime()
    original_eval = queue.eval
    attempts = 0

    def fail_once(script: str, numkeys: int, *keys_and_args: str) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("redis unavailable")
        return original_eval(script, numkeys, *keys_and_args)

    queue.eval = fail_once  # type: ignore[method-assign]
    request = JobRequest("demo", {}, "repair-dispatch")
    try:
        dispatcher.submit(request)
    except ConnectionError:
        pass
    else:  # pragma: no cover - protects the intended failure setup
        raise AssertionError("first dispatch should fail")

    retried = dispatcher.submit(request)
    assert retried.id == request.job_id
    assert len(queue._items) == 1  # noqa: SLF001 - inspect durable fake state


def test_worker_records_success_and_supports_cancellation() -> None:
    repository, dispatcher, _ = _runtime()

    def handler(context) -> None:
        context.progress(0.25, "started", event_key="work-start")
        context.progress(0.75, "almost done", event_key="work-almost")

    request = JobRequest("demo", {}, "success")
    dispatcher.submit(request)
    worker = JobWorker(dispatcher, {"demo": handler})
    assert worker.run_once()
    receipt = repository.get(request.job_id)
    assert receipt is not None
    assert receipt.status == JobStatus.SUCCEEDED
    assert receipt.progress == 1.0

    cancelled = JobRequest("demo", {}, "cancelled")
    dispatcher.submit(cancelled)
    assert dispatcher.cancel(cancelled.job_id)
    assert worker.run_once()
    assert repository.get(cancelled.job_id).status == JobStatus.CANCELED


def test_worker_marks_handler_cancellation_and_restart_requeues_once() -> None:
    repository, dispatcher, queue = _runtime()
    request = JobRequest("demo", {}, "handler-cancel")
    dispatcher.submit(request)

    def handler(context) -> None:
        dispatcher.cancel(context.job_id)
        raise JobCancelled("stop")

    worker = JobWorker(dispatcher, {"demo": handler})
    assert worker.run_once()
    assert repository.get(request.job_id).status == JobStatus.CANCELED

    recovering = JobRequest("demo", {}, "recover")
    dispatcher.submit(recovering)
    repository.update_status(recovering.job_id, JobStatus.RUNNING)
    assert worker.recover() == [recovering.job_id]
    assert worker.recover() == []
    assert queue.blpop(dispatcher.queue_name) is not None


def test_worker_reclaims_unacknowledged_message_without_duplicate_events() -> None:
    repository, dispatcher, queue = _runtime()
    request = JobRequest("demo", {}, "interrupted")
    dispatcher.submit(request)

    encoded = queue.brpoplpush(
        dispatcher.queue_name,
        f"{dispatcher.queue_name}:processing",
    )
    assert encoded is not None
    repository.update_status(request.job_id, JobStatus.RUNNING)
    repository.append_event(
        JobEvent(request.job_id, JobEventType.STARTED, f"{request.job_id}:started")
    )

    worker = JobWorker(dispatcher, {"demo": lambda context: None})
    assert worker.recover() == [request.job_id]
    assert worker.run_once()
    assert repository.get(request.job_id).status == JobStatus.SUCCEEDED
    event_keys = [event.event_key for event in repository.list_events(request.job_id)]
    assert len(event_keys) == len(set(event_keys))
    assert queue._processing == []  # noqa: SLF001 - verify the fake acknowledgement path


def test_health_probes_are_safe_and_readiness_is_explicit() -> None:
    good = probe("memory", lambda: True)
    bad = probe("broken", lambda: (_ for _ in ()).throw(RuntimeError("secret detail")))
    assert good == DependencyHealth("memory", True, "ready")
    assert bad.detail == "RuntimeError"
    assert readiness([good, bad])[0] is False


def test_event_metadata_is_deterministically_serializable() -> None:
    event = JobEvent("job", JobEventType.PROGRESS, "key", metadata={"b": 2, "a": 1})
    serialized = canonical_json(event.to_dict())
    assert '"metadata":{"a":1,"b":2}' in serialized
