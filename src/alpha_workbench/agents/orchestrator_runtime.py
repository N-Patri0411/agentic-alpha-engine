"""Bounded LangGraph wiring around the standalone agent callables.

The graph is an execution shell only. Routing is checked by
``OrchestratorPolicy`` and handlers are explicitly injected, so this module
cannot discover tools or access arbitrary network/graph resources.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

from .contracts import AgentRequest, AgentResult, AgentRun, NextAction, RunBudget
from .orchestrator import OrchestratorAgent, RunEventLedger

Handler = Callable[[AgentRequest], AgentResult]


class RetryableActionError(RuntimeError):
    """A transient handler failure eligible for bounded retry."""


class OrchestratorState(TypedDict, total=False):
    run: AgentRun
    context: str
    payload: dict[str, object]
    current_action: str
    last_result: AgentResult
    failure: str


_RUNNABLE_ACTIONS = {
    "extraction",
    "graph_adjudicator",
    "alpha_generator",
    "backtester",
    "gatekeeper",
    "portfolio_optimiser",
    "monitor",
    "research",
}


def build_bounded_orchestrator_graph(
    router: OrchestratorAgent,
    handlers: Mapping[str, Handler],
    *,
    ledger: RunEventLedger | None = None,
) -> Any:
    """Compile a bounded LangGraph workflow with explicitly injected handlers.

    ``handlers`` is the only execution capability available to the graph. A
    missing handler pauses the run. The caller supplies a preconfigured
    ``OrchestratorAgent`` (and therefore the model boundary); no vendor SDK is
    imported here.
    """

    try:
        from langgraph.graph import END, StateGraph
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError("install the [agents] extra to use LangGraph orchestration") from error

    def route(state: OrchestratorState) -> OrchestratorState:
        run = state["run"]
        if state.get("failure") and state.get("current_action") in _RUNNABLE_ACTIONS:
            # A retry has already been recorded. Do not spend another model
            # call or ask the model to invent a self-transition.
            return {"run": run, "current_action": state["current_action"]}
        action = router.choose_next(run, state.get("context", ""))
        updated = router.record_action(
            run,
            action,
            state.get("context", ""),
            ledger=ledger,
        )
        return {"run": updated, "current_action": action.action}

    def make_action_node(action_name: str) -> Callable[[OrchestratorState], OrchestratorState]:
        def action_node(state: OrchestratorState) -> OrchestratorState:
            run = state["run"]
            handler = handlers.get(action_name)
            if handler is None:
                pause = NextAction(
                    action="pause_for_review", reason=f"no handler registered for {action_name}"
                )
                return {"run": router.record_action(run, pause, f"missing-handler:{action_name}")}
            request = AgentRequest(
                run_id=run.id,
                agent=action_name,  # type: ignore[arg-type]
                payload=state.get("payload", {}),
            )
            try:
                result = handler(request)
            except RetryableActionError as error:
                retry = NextAction(action=action_name, reason=f"retryable failure: {error}")  # type: ignore[arg-type]
                updated = router.record_action(
                    run, retry, state.get("context", ""), ledger=ledger, retry=True
                )
                return {"run": updated, "current_action": action_name, "failure": str(error)}
            except Exception as error:  # fail closed; unknown failures require review
                pause = NextAction(action="pause_for_review", reason=f"handler failed: {error}")
                updated = router.record_action(
                    run, pause, f"failure:{action_name}:{error}", ledger=ledger
                )
                return {"run": updated, "failure": str(error)}
            if result.status != "completed":
                pause = NextAction(
                    action="pause_for_review", reason=f"{action_name} returned {result.status}"
                )
                updated = router.record_action(
                    run, pause, f"result:{action_name}:{result.message}", ledger=ledger
                )
                return {"run": updated, "last_result": result}
            return {"run": run, "last_result": result, "failure": ""}

        return action_node

    def route_next(state: OrchestratorState) -> str:
        run = state["run"]
        if run.status in {"paused", "completed", "loop_detected", "failed"}:
            return END
        action = state.get("current_action", "pause_for_review")
        if action in {"complete", "pause_for_review"}:
            return END
        if action not in _RUNNABLE_ACTIONS:
            return END
        return action

    graph = StateGraph(OrchestratorState)
    graph.add_node("route", route)
    for action_name in _RUNNABLE_ACTIONS:
        graph.add_node(action_name, cast(Any, make_action_node(action_name)))
        graph.add_edge(action_name, "route")
    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route", route_next, {**{name: name for name in _RUNNABLE_ACTIONS}, END: END}
    )
    return graph.compile()


def run_bounded_workflow(
    router: OrchestratorAgent,
    handlers: Mapping[str, Handler],
    *,
    run_id: str,
    context: str,
    payload: dict[str, object] | None = None,
    budget: RunBudget | None = None,
    ledger: RunEventLedger | None = None,
) -> OrchestratorState:
    """Run one bounded workflow and return the serializable final state."""

    graph = build_bounded_orchestrator_graph(router, handlers, ledger=ledger)
    initial: OrchestratorState = {
        "run": AgentRun(
            id=run_id,
            status="pending",
            created_at=datetime.now(UTC),
            budget=budget or RunBudget(),
        ),
        "context": context,
        "payload": payload or {},
    }
    return cast(
        OrchestratorState,
        graph.invoke(
            initial,
            config={"recursion_limit": (initial["run"].budget.max_steps * 3) + 4},
        ),
    )
