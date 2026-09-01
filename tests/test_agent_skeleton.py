from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_workbench.agents import (
    AlphaGeneratorAgent,
    BacktesterAgent,
    ExtractionAgent,
    GatekeeperAgent,
    MonitorAgent,
    PortfolioOptimiserAgent,
    ResearchAgent,
)
from alpha_workbench.agents.contracts import AgentRequest, AgentRun
from alpha_workbench.agents.orchestrator import OrchestratorAgent
from alpha_workbench.llm.models import FakeLLMClient, create_llm, load_model_config
from alpha_workbench.server.app import health, start_run


@pytest.mark.parametrize(
    ("agent", "name"),
    [
        (ExtractionAgent(), "extraction"),
        (AlphaGeneratorAgent(), "alpha_generator"),
        (BacktesterAgent(), "backtester"),
        (GatekeeperAgent(), "gatekeeper"),
        (PortfolioOptimiserAgent(), "portfolio_optimiser"),
        (MonitorAgent(), "monitor"),
        (ResearchAgent(), "research"),
    ],
)
def test_agent_skeletons_are_individually_callable(agent: object, name: str) -> None:
    request = AgentRequest(run_id="run-1", agent=name)  # type: ignore[arg-type]
    result = agent.run(request)  # type: ignore[union-attr]
    assert result.status == "completed"
    assert result.agent == name


def test_fake_model_is_loaded_from_role_config() -> None:
    path = Path("config/models.yaml")
    client = create_llm(load_model_config(path, "orchestrator"))
    assert client.complete_json(system="test", user="test")["action"] == "complete"


def test_orchestrator_detects_repeated_action_with_same_input() -> None:
    router = OrchestratorAgent(FakeLLMClient({"action": "extraction", "reason": "new document"}))
    run = AgentRun(id="run-1", created_at=datetime.now(UTC))
    action = router.choose_next(run, "start")
    run = router.record_action(run, action, "same input")
    run = router.record_action(run, action, "same input")
    stopped = router.record_action(run, action, "same input")
    assert stopped.status == "loop_detected"


def test_local_api_creates_a_stub_run() -> None:
    from alpha_workbench.server.app import StartRunRequest, get_run

    assert health()["status"] == "ok"
    created = start_run(StartRunRequest(name="manual demo"))
    assert get_run(created.id).id == created.id
