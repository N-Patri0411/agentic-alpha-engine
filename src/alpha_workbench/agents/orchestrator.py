"""Bounded policy and model-assisted routing for the research workflow.

The language model may suggest the next *named* action, but this module owns
the safety boundary. It never executes tools, accepts URLs, writes graph files,
or makes portfolio decisions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb
from pydantic import BaseModel, Field

from ..llm.models import LLMClient
from .contracts import AgentRun, NextAction, RunEvent

ActionName = Literal[
    "extraction",
    "graph_adjudicator",
    "alpha_generator",
    "backtester",
    "gatekeeper",
    "portfolio_optimiser",
    "monitor",
    "research",
    "complete",
    "pause_for_review",
]

_ALLOWED_ACTIONS = {
    "extraction",
    "graph_adjudicator",
    "alpha_generator",
    "backtester",
    "gatekeeper",
    "portfolio_optimiser",
    "monitor",
    "research",
    "complete",
    "pause_for_review",
}

_TRANSITIONS: dict[str | None, set[str]] = {
    None: {"extraction", "alpha_generator", "monitor", "research", "complete", "pause_for_review"},
    "extraction": {"graph_adjudicator", "alpha_generator", "complete", "pause_for_review"},
    "graph_adjudicator": {"alpha_generator", "complete", "pause_for_review"},
    "alpha_generator": {"backtester", "complete", "pause_for_review"},
    "backtester": {"gatekeeper", "complete", "pause_for_review"},
    "gatekeeper": {"portfolio_optimiser", "alpha_generator", "complete", "pause_for_review"},
    "portfolio_optimiser": {"complete", "pause_for_review"},
    "monitor": {"gatekeeper", "research", "complete", "pause_for_review"},
    "research": {"extraction", "monitor", "complete", "pause_for_review"},
    "complete": set(),
    "pause_for_review": set(),
}


class RouteDecision(BaseModel):
    """Auditable outcome of a proposed route."""

    action: NextAction
    status: Literal["routed", "paused", "completed", "loop_detected"]
    reason: str = Field(min_length=1)
    input_hash: str
    idempotency_key: str


class OrchestratorPolicy:
    """Pure deterministic checks for route, budget, and retry safety."""

    def validate_transition(
        self, previous: str | None, proposed: str, *, retry: bool = False
    ) -> str | None:
        if proposed not in _ALLOWED_ACTIONS:
            return f"action {proposed!r} is not allowlisted"
        if retry:
            if previous != proposed:
                return "retry must repeat the failed action"
            return None
        if proposed not in _TRANSITIONS.get(previous, set()):
            return f"transition {previous or 'start'} -> {proposed} is not approved"
        return None

    def budget_reason(self, run: AgentRun, now: datetime | None = None) -> str | None:
        if run.steps >= run.budget.max_steps:
            return "workflow step budget exhausted"
        if run.llm_calls >= run.budget.max_llm_calls:
            return "LLM call budget exhausted"
        current = now or datetime.now(UTC)
        elapsed = (current - run.created_at).total_seconds()
        if elapsed > run.budget.max_runtime_seconds:
            return "workflow wall-clock budget exhausted"
        return None

    def input_hash(self, input_text: str) -> str:
        return hashlib.sha256(input_text.encode("utf-8")).hexdigest()

    def idempotency_key(self, run_id: str, action: str, input_hash: str) -> str:
        return hashlib.sha256(f"{run_id}:{action}:{input_hash}".encode()).hexdigest()


class RunEventLedger:
    """Small append-only event ledger for durable run accounting."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path)) as connection:
            connection.execute(
                """
                create table if not exists orchestrator_events (
                    idempotency_key varchar primary key,
                    run_id varchar not null,
                    action varchar not null,
                    input_hash varchar not null,
                    event_at timestamp with time zone not null,
                    detail varchar not null
                )
                """
            )

    def append(self, run_id: str, event: RunEvent) -> bool:
        with duckdb.connect(str(self.path)) as connection:
            result = connection.execute(
                """
                insert into orchestrator_events
                    (idempotency_key, run_id, action, input_hash, event_at, detail)
                values (?, ?, ?, ?, ?, ?)
                on conflict (idempotency_key) do nothing
                """,
                [
                    event.idempotency_key,
                    run_id,
                    event.action,
                    event.input_hash,
                    event.at,
                    event.detail,
                ],
            )
            return result.rowcount == 1


class OrchestratorAgent:
    """LLM-assisted router bounded by deterministic policy checks."""

    name = "orchestrator"

    def __init__(self, llm: LLMClient, *, policy: OrchestratorPolicy | None = None) -> None:
        self._llm = llm
        self.policy = policy or OrchestratorPolicy()

    def choose_next(self, run: AgentRun, context: str) -> NextAction:
        """Ask the model for a route, converting unsafe output into a pause."""

        reason = self.policy.budget_reason(run)
        if reason:
            return NextAction(action="pause_for_review", reason=reason)
        previous = run.events[-1].action if run.events else None
        try:
            raw = self._llm.complete_json(
                system=(
                    "You route a bounded paper-research workflow. Choose exactly one action "
                    "from the allowed action list. You cannot publish graph edges, alter budgets, "
                    "execute shell commands, call arbitrary URLs, accept signals, or trade. "
                    "Return JSON with action and reason."
                ),
                user=context,
            )
            action = NextAction.model_validate(raw)
            error = self.policy.validate_transition(previous, action.action)
            if error:
                return NextAction(action="pause_for_review", reason=f"route rejected: {error}")
            return action
        except Exception as error:  # malformed model output must stop safely
            return NextAction(action="pause_for_review", reason=f"invalid model route: {error}")

    def record_action(
        self,
        run: AgentRun,
        action: NextAction,
        input_text: str,
        *,
        ledger: RunEventLedger | None = None,
        retry: bool = False,
    ) -> AgentRun:
        """Record one idempotent action, or stop a repeated-action loop."""

        if run.status in {"completed", "failed", "loop_detected"}:
            return run
        digest = self.policy.input_hash(input_text)
        previous = run.events[-1].action if run.events else None
        repeats = sum(
            event.action == action.action and event.input_hash == digest for event in run.events
        )
        if repeats >= 2:
            return run.model_copy(update={"status": "loop_detected"})
        # Re-delivery of the identical action/input is treated as an implicit
        # bounded retry for compatibility with the durable idempotency model.
        transition_error = self.policy.validate_transition(
            previous, action.action, retry=retry or (previous == action.action and repeats < 2)
        )
        if transition_error:
            return run.model_copy(update={"status": "paused"})
        budget_reason = self.policy.budget_reason(run)
        if budget_reason:
            return run.model_copy(update={"status": "paused"})
        event = RunEvent(
            at=datetime.now(UTC),
            action=action.action,
            input_hash=digest,
            idempotency_key=self.policy.idempotency_key(run.id, action.action, digest),
            detail=action.reason,
        )
        if ledger is not None:
            ledger.append(run.id, event)
        status = (
            "completed"
            if action.action == "complete"
            else "paused"
            if action.action == "pause_for_review"
            else "running"
        )
        return run.model_copy(
            update={
                "status": status,
                "steps": run.steps + 1,
                "llm_calls": run.llm_calls + (0 if retry else 1),
                "events": [*run.events, event],
            }
        )

    def resume(self, run: AgentRun) -> AgentRun:
        """Explicitly resume a paused run without clearing its audit history."""

        if run.status != "paused":
            raise ValueError("only a paused run can be resumed")
        return run.model_copy(update={"status": "running"})
