from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alpha_workbench.agents.contracts import AgentResult, AgentRun, RunBudget
from alpha_workbench.agents.orchestrator import (
    OrchestratorAgent,
    OrchestratorPolicy,
    RunEventLedger,
)
from alpha_workbench.agents.orchestrator_runtime import (
    RetryableActionError,
    run_bounded_workflow,
)


class SequenceLLM:
    def __init__(self, actions: list[str]) -> None:
        self.actions = iter(actions)

    def complete_json(self, *, system: str, user: str) -> dict[str, str]:
        del system, user
        action = next(self.actions)
        return {"action": action, "reason": "test route"}


def _handlers() -> dict[str, object]:
    def run(request):
        return AgentResult(
            run_id=request.run_id,
            agent=request.agent,
            status="completed",
            message="ok",
            latency_ms=0,
        )

    return {name: run for name in (
        "extraction", "graph_adjudicator", "alpha_generator", "backtester",
        "gatekeeper", "portfolio_optimiser", "monitor", "research",
    )}


def test_policy_rejects_gate_skipping_and_wall_clock() -> None:
    policy = OrchestratorPolicy()
    assert policy.validate_transition("extraction", "portfolio_optimiser")
    run = AgentRun(
        id="budget",
        created_at=datetime.now(UTC) - timedelta(seconds=10),
        budget=RunBudget(max_runtime_seconds=1),
    )
    assert policy.budget_reason(run) == "workflow wall-clock budget exhausted"


def test_langgraph_routes_valid_pipeline_and_writes_idempotent_ledger(tmp_path: Path) -> None:
    router = OrchestratorAgent(SequenceLLM([
        "extraction", "graph_adjudicator", "alpha_generator", "backtester",
        "gatekeeper", "portfolio_optimiser", "complete",
    ]))
    ledger = RunEventLedger(tmp_path / "runs.duckdb")
    state = run_bounded_workflow(
        router, _handlers(), run_id="valid", context="semiconductor run", ledger=ledger
    )
    assert state["run"].status == "completed"
    assert state["run"].steps == 7
    assert len(state["run"].events) == 7
    with __import__("duckdb").connect(str(tmp_path / "runs.duckdb")) as connection:
        assert connection.execute("select count(*) from orchestrator_events").fetchone()[0] == 7


def test_invalid_model_route_pauses_without_running_handler() -> None:
    router = OrchestratorAgent(SequenceLLM(["backtester"]))
    state = run_bounded_workflow(router, _handlers(), run_id="invalid", context="bad")
    assert state["run"].status == "paused"
    assert "route rejected" in state["run"].events[0].detail


def test_step_budget_pauses_after_first_action() -> None:
    router = OrchestratorAgent(SequenceLLM(["extraction", "complete"]))
    state = run_bounded_workflow(
        router,
        _handlers(),
        run_id="small",
        context="budget",
        budget=RunBudget(max_steps=1),
    )
    assert state["run"].status == "paused"
    assert state["run"].steps == 1


def test_retryable_failure_retries_once_then_continues() -> None:
    router = OrchestratorAgent(SequenceLLM(["extraction", "complete"]))
    attempts = 0

    def flaky(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RetryableActionError("temporary source outage")
        return AgentResult(
            run_id=request.run_id,
            agent=request.agent,
            status="completed",
            message="recovered",
            latency_ms=0,
        )

    handlers = _handlers()
    handlers["extraction"] = flaky
    state = run_bounded_workflow(router, handlers, run_id="retry", context="source")
    assert state["run"].status == "completed"
    assert attempts == 2


def test_pause_resume_preserves_audit_history() -> None:
    router = OrchestratorAgent(SequenceLLM(["backtester"]))
    state = run_bounded_workflow(router, _handlers(), run_id="resume", context="bad")
    paused = state["run"]
    resumed = router.resume(paused)
    assert resumed.status == "running"
    assert resumed.steps == paused.steps
    assert len(resumed.events) == len(paused.events)
    with pytest.raises(ValueError):
        router.resume(resumed)
