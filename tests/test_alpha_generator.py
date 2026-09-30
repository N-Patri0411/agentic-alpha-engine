from datetime import UTC, datetime

import pytest

from alpha_workbench.agents.alpha_generator import AlphaGeneratorAgent
from alpha_workbench.agents.contracts import AgentRequest
from alpha_workbench.alpha.dsl import DSLValidationError, parse_expression
from alpha_workbench.llm.models import FakeLLMClient


def request(payload: dict[str, object]) -> AgentRequest:
    return AgentRequest(run_id="alpha-test", agent="alpha_generator", payload=payload)


def test_generator_accepts_typed_candidate_and_records_provenance() -> None:
    agent = AlphaGeneratorAgent(
        FakeLLMClient(
            {
                "candidates": [
                    {
                        "id": "momentum-1",
                        "expression": "Rank(momentum)",
                        "rationale": "ranked recent movement",
                    }
                ]
            }
        )
    )
    result = agent.generate(
        request({"features": [{"name": "momentum", "source_artifact_ids": ["obs-1"]}]})
    )
    assert result.candidates[0].provenance.feature_names == ["momentum"]
    assert result.candidates[0].provenance.source_artifact_ids == ["obs-1"]


def test_generator_accepts_common_formula_reason_aliases_and_reports_keys_only() -> None:
    agent = AlphaGeneratorAgent(
        FakeLLMClient(
            {
                "candidates": [
                    {"formula": "Rank(momentum)", "reason": "alias response"},
                    {"expression": "Rank(momentum)"},
                ]
            }
        )
    )
    result = agent.generate(request({"features": ["momentum"]}))
    assert len(result.candidates) == 1
    assert "keys=['expression']" in result.rejected[0]
    assert "alias response" not in result.rejected[0]


def test_generator_rejects_unsafe_expression_without_evaluation() -> None:
    agent = AlphaGeneratorAgent(
        FakeLLMClient(
            {
                "candidates": [
                    {
                        "expression": "__import__('os').system('x')",
                        "rationale": "bad",
                    }
                ]
            }
        )
    )
    result = agent.generate(request({"features": ["momentum"]}))
    assert not result.candidates
    assert "unsupported syntax" in result.rejected[0]


def test_generator_rejects_future_feature_at_as_of_time() -> None:
    agent = AlphaGeneratorAgent(FakeLLMClient())
    with pytest.raises(ValueError, match="unavailable"):
        agent.generate(
            request(
                {
                    "as_of_time": datetime(2024, 1, 1, tzinfo=UTC),
                    "features": [{"name": "news", "available_at": "2024-01-02T00:00:00Z"}],
                }
            )
        )


def test_dsl_whitelist_and_rendering() -> None:
    expression = parse_expression("Add(Rank(momentum),Neg(value))", {"momentum", "value"})
    assert expression.render() == "Add(Rank(momentum),Neg(value))"
    with pytest.raises(DSLValidationError):
        parse_expression("Power(value,2)", {"value"})
