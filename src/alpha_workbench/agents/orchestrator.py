"""Bounded agentic routing policy used before LangGraph wiring in Phase 5."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from ..llm.models import LLMClient
from .contracts import AgentRun, NextAction, RunEvent

_ALLOWED_ACTIONS = {
    "extraction",
    "alpha_generator",
    "backtester",
    "gatekeeper",
    "portfolio_optimiser",
    "monitor",
    "research",
    "complete",
    "pause_for_review",
}


class OrchestratorAgent:
    """LLM-assisted router bounded by deterministic budgets and loop detection.

    This class never executes tools. Future LangGraph nodes will consume its
    ``NextAction`` only after the policy checks here succeed.
    """

    name = "orchestrator"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def choose_next(self, run: AgentRun, context: str) -> NextAction:
        if run.steps >= run.budget.max_steps:
            return NextAction(action="pause_for_review", reason="workflow step budget exhausted")
        if run.llm_calls >= run.budget.max_llm_calls:
            return NextAction(action="pause_for_review", reason="LLM call budget exhausted")
        raw = self._llm.complete_json(
            system=(
                "You route a research workflow. Choose exactly one allowed action. "
                "You cannot publish graph edges, alter budgets, execute shell commands, "
                "or call unlisted tools. Return JSON with action and reason."
            ),
            user=context,
        )
        action = NextAction.model_validate(raw)
        if action.action not in _ALLOWED_ACTIONS:  # defensive for future schema changes
            raise ValueError(f"orchestrator chose disallowed action {action.action!r}")
        return action

    def record_action(self, run: AgentRun, action: NextAction, input_text: str) -> AgentRun:
        """Append one idempotent event or terminate a repeated-action loop."""

        digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        repeats = sum(
            event.action == action.action and event.input_hash == digest for event in run.events
        )
        if repeats >= 2:
            return run.model_copy(update={"status": "loop_detected"})
        event = RunEvent(
            at=datetime.now(UTC),
            action=action.action,
            input_hash=digest,
            idempotency_key=hashlib.sha256(
                f"{run.id}:{action.action}:{digest}".encode()
            ).hexdigest(),
            detail=action.reason,
        )
        return run.model_copy(
            update={
                "status": "running",
                "steps": run.steps + 1,
                "llm_calls": run.llm_calls + 1,
                "events": [*run.events, event],
            }
        )
