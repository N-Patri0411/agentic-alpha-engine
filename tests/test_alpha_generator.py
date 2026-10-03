from datetime import UTC, datetime

import pytest

from alpha_workbench.agents.alpha_generator import (
    AlphaGeneratorAgent,
    AlphaGeneratorService,
    InMemoryTrialLedger,
)
from alpha_workbench.agents.contracts import AgentRequest
from alpha_workbench.alpha import AdvancedPythonExtensionRegistry, ExtensionPolicyError
from alpha_workbench.alpha.dsl import (
    DSLValidationError,
    canonicalize_expression,
    parse_expression,
)
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


def test_canonical_formulas_dedupe_commutative_terms_and_numeric_format() -> None:
    assert canonicalize_expression(" Add(0.50, momentum) ", {"momentum"}) == (
        "Add(0.5,momentum)"
    )
    agent = AlphaGeneratorAgent(
        FakeLLMClient({
            "candidates": [
                {"id": "one", "expression": "Add(momentum,value)", "rationale": "a"},
                {"id": "two", "expression": "Add(value,momentum)", "rationale": "b"},
            ]
        })
    )
    result = agent.generate(request({"features": ["momentum", "value"]}))
    assert len(result.candidates) == 1
    assert "duplicate candidate" in result.rejected[0]


def test_frequency_mismatch_and_incompatible_axis_are_rejected() -> None:
    with pytest.raises(ValueError, match="frequency mismatch"):
        AlphaGeneratorAgent(FakeLLMClient()).generate(
            request({
                "frequency": "weekly",
                "features": [{"name": "momentum", "frequency": "daily"}],
            })
        )
    result = AlphaGeneratorAgent(
        FakeLLMClient({
            "candidates": [{
                "expression": "Rank(momentum)",
                "rationale": "axis incompatible",
            }]
        })
    ).generate(request({
        "features": [{"name": "momentum", "supported_axes": ["time_series"]}]
    }))
    assert not result.candidates
    assert "cross_section-compatible" in result.rejected[0]


def test_quarterly_feature_requires_explicit_release_mapping_for_monthly_signal() -> None:
    as_of = datetime(2024, 6, 30, tzinfo=UTC)
    feature = {
        "name": "quarterly_value",
        "frequency": "quarterly",
        "available_at": "2024-05-01T00:00:00Z",
    }
    agent = AlphaGeneratorAgent(FakeLLMClient({
        "candidates": [{"expression": "Rank(quarterly_value)", "rationale": "released data"}]
    }))
    with pytest.raises(ValueError, match="frequency mismatch"):
        agent.generate(request({
            "frequency": "monthly", "as_of_time": as_of, "features": [feature]
        }))
    result = agent.generate(request({
        "frequency": "monthly",
        "feature_frequency_policy": "quarterly_release_to_monthly",
        "as_of_time": as_of,
        "features": [feature],
    }))
    assert len(result.candidates) == 1
    assert result.candidates[0].signal is not None
    strategy = result.candidates[0].signal.to_strategy_spec(
        strategy_id="s1", workspace_id="w1", universe_id="u1", name="monthly"
    )
    assert strategy.validation_config["feature_frequency_policy"] == (
        "quarterly_release_to_monthly"
    )
    with pytest.raises(ValueError, match="frequency mismatch"):
        agent.generate(request({
            "frequency": "monthly",
            "feature_frequency_policy": "quarterly_release_to_monthly",
            "as_of_time": as_of,
            "features": [{"name": "quarterly_value", "frequency": "quarterly"}],
        }))


def test_unavailable_feature_rejected_and_pins_flow_to_product_strategy() -> None:
    with pytest.raises(ValueError, match="unavailable"):
        AlphaGeneratorAgent(FakeLLMClient()).generate(
            request({"features": [{"name": "momentum", "available": False}]})
        )
    result = AlphaGeneratorAgent(FakeLLMClient({
        "candidates": [{"expression": "Rank(momentum)", "rationale": "pinned"}]
    })).generate(request({
        "frequency": "weekly",
        "graph_version_id": "graph-v7",
        "features": [{
            "name": "momentum",
            "frequency": "weekly",
            "feature_version_id": "feature-v2",
            "dataset_version_id": "dataset-v3",
            "source_artifact_ids": ["source-1"],
        }],
    }))
    signal = result.candidates[0].signal
    assert signal is not None
    assert signal.graph_version_id == "graph-v7"
    strategy = signal.to_strategy_spec(
        strategy_id="s1", workspace_id="w1", universe_id="u1", name="weekly signal"
    )
    assert strategy.cadence == "weekly"
    assert strategy.dataset_version_ids == ("dataset-v3",)
    assert strategy.graph_version_id == "graph-v7"
    assert strategy.signal_expression == "Rank(momentum)"


def test_experiment_trial_ledger_counts_unique_canonical_formulas() -> None:
    ledger = InMemoryTrialLedger()
    first = AlphaGeneratorService(
        AlphaGeneratorAgent(FakeLLMClient({"candidates": [
            {"id": "a", "expression": "Add(x,y)", "rationale": "one"},
        ]})),
        ledger,
    ).generate({"features": ["x", "y"]}, experiment_id="exp", trial_limit=1)
    duplicate = AlphaGeneratorService(
        AlphaGeneratorAgent(FakeLLMClient({"candidates": [
            {"id": "b", "expression": "Add(y,x)", "rationale": "same trial"},
        ]})),
        ledger,
    ).generate({"features": ["x", "y"]}, experiment_id="exp", trial_limit=1)
    over_budget = AlphaGeneratorService(
        AlphaGeneratorAgent(FakeLLMClient({"candidates": [
            {"id": "c", "expression": "Sub(x,y)", "rationale": "new trial"},
        ]})),
        ledger,
    ).generate({"features": ["x", "y"]}, experiment_id="exp", trial_limit=1)
    assert len(first.candidates) == 1
    assert not duplicate.candidates
    assert not over_budget.candidates
    assert first.trial_count == duplicate.trial_count == over_budget.trial_count == 1
    assert "before model generation" in duplicate.rejected[0]
    assert "trial limit exceeded" in over_budget.rejected[0]


def test_bounded_candidate_batch_and_disabled_extension_contract() -> None:
    too_many = {"candidates": [
        {"id": f"c{i}", "expression": f"Rank({'x' if i % 2 == 0 else 'y'})", "rationale": "bounded"}
        for i in range(4)
    ]}
    result = AlphaGeneratorAgent(FakeLLMClient(too_many), max_candidates=1).generate(
        request({"features": ["x", "y"]})
    )
    assert len(result.candidates) == 1
    assert "bounded limit" in result.rejected[0]
    with pytest.raises(ExtensionPolicyError, match="disabled"):
        AdvancedPythonExtensionRegistry().register("operator", abs, pinned_sha256="0" * 64)


def _trusted_test_extension(value: float) -> float:
    return value


def test_hash_pinned_extension_requires_explicit_registration() -> None:
    registry = AdvancedPythonExtensionRegistry(enabled=True)
    source_hash = registry.source_hash(_trusted_test_extension)
    item = registry.register(
        "trusted_test_extension", _trusted_test_extension, pinned_sha256=source_hash
    )
    assert registry.resolve(item.name, pinned_sha256=source_hash) is item
    with pytest.raises(ExtensionPolicyError, match="not explicitly registered"):
        registry.resolve(item.name, pinned_sha256="0" * 64)
