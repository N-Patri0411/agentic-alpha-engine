from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from alpha_workbench.agents.backtester_agent import BacktesterAgent
from alpha_workbench.agents.contracts import AgentRequest
from alpha_workbench.alpha.evaluator import evaluate_factor_expression
from alpha_workbench.data import PointInTimeViolation
from alpha_workbench.graph_features import graph_ripple_factors
from alpha_workbench.graph_registry import GraphSnapshot, RippleRiskScorer

SNAPSHOT = GraphSnapshot.from_json(Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json"))


def test_graph_feature_emits_backtest_schema_and_stable_receipt() -> None:
    dates = [datetime(2026, 9, 2, tzinfo=UTC)]
    kwargs = {
        "dates": dates,
        "tickers": ["NVDA", "AMD", "TSM"],
        "shock_entity_id": "TSM",
        "as_of_time": datetime(2026, 9, 2, tzinfo=UTC),
    }
    first, receipt_one = graph_ripple_factors(SNAPSHOT, **kwargs)
    second, receipt_two = graph_ripple_factors(SNAPSHOT, **kwargs)
    assert list(first.columns) == ["date", "ticker", "score", "available_at"]
    assert first.equals(second)
    assert receipt_one.receipt_sha256 == receipt_two.receipt_sha256
    assert first.set_index("ticker").loc["NVDA", "score"] > 0
    assert first.set_index("ticker").loc["TSM", "score"] == 0


def test_graph_feature_rejects_snapshot_not_available_on_signal_date() -> None:
    with pytest.raises(PointInTimeViolation):
        graph_ripple_factors(
            SNAPSHOT,
            dates=[datetime(2026, 2, 10, tzinfo=UTC)],
            tickers=["NVDA"],
            shock_entity_id="TSM",
            as_of_time=datetime(2026, 9, 2, tzinfo=UTC),
        )


def test_graph_scorer_can_exclude_non_causal_candidate_relationships() -> None:
    result = RippleRiskScorer(SNAPSHOT).score(
        shock_entity_id="TSM",
        severity=1.0,
        as_of_time=datetime(2026, 9, 2, tzinfo=UTC),
        relationship_types={"competitive_substitution"},
    )
    assert result.impacts == []


def test_backtester_agent_reports_candidate_against_baseline() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"] * 2),
            "ticker": ["A", "A", "B", "B"],
            "close": [100, 110, 100, 90],
            "available_at": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z"] * 2,
        }
    )
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"] * 2),
            "ticker": ["A", "B"],
            "score": [1.0, -1.0],
            "available_at": ["2024-01-02T20:00:00Z"] * 2,
        }
    )
    evaluation = BacktesterAgent().evaluate(
        prices, factors, as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC)
    )
    assert evaluation.receipt_sha256
    assert evaluation.candidate.report.periods == evaluation.baseline.report.periods
    assert (
        evaluation.candidate.report.net_return - evaluation.baseline.report.net_return
        == pytest.approx(0)
    )


def test_backtester_agent_empty_request_keeps_safe_compatibility() -> None:
    result = BacktesterAgent().run(AgentRequest(run_id="x", agent="backtester"))
    assert result.status == "completed"


def test_backtester_accepts_validated_alpha_dsl_expression() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"] * 2),
            "ticker": ["A", "A", "B", "B"],
            "close": [100, 110, 100, 90],
            "available_at": ["2024-01-02T21:00:00Z", "2024-01-03T21:00:00Z"] * 2,
        }
    )
    features = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"] * 2),
            "ticker": ["A", "B"],
            "graph_ripple_risk": [0.2, 0.8],
            "available_at": ["2024-01-02T20:00:00Z"] * 2,
        }
    )
    result = BacktesterAgent().evaluate_candidate_expression(
        prices,
        features,
        expression="Neg(graph_ripple_risk)",
        feature_names={"graph_ripple_risk"},
        as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC),
    )
    assert result.candidate.report.periods == 1


def test_backtester_rejects_signal_after_execution_price() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"] * 2),
            "ticker": ["A", "A", "B", "B"],
            "close": [100, 110, 100, 90],
            "available_at": ["2024-01-02T20:00:00Z", "2024-01-03T21:00:00Z"] * 2,
        }
    )
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"] * 2),
            "ticker": ["A", "B"],
            "score": [1.0, -1.0],
            "available_at": ["2024-01-02T21:00:00Z"] * 2,
        }
    )
    with pytest.raises(PointInTimeViolation):
        BacktesterAgent().evaluate(
            prices, factors, as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC)
        )


def test_backtester_rejects_future_signal_date() -> None:
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-04"] * 2),
            "ticker": ["A", "B"],
            "score": [1.0, -1.0],
            "available_at": ["2024-01-03T20:00:00Z"] * 2,
        }
    )
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-04", "2024-01-05"] * 2),
            "ticker": ["A", "A", "B", "B"],
            "close": [100, 110, 100, 90],
            "available_at": ["2024-01-03T20:00:00Z", "2024-01-03T20:00:00Z"] * 2,
        }
    )
    with pytest.raises(ValueError, match="signal dates"):
        BacktesterAgent().evaluate(
            prices, factors, as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC)
        )


def test_dsl_time_series_operators_are_deterministic_and_safe() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"] * 2),
            "ticker": ["A"] * 3 + ["B"] * 3,
            "x": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
            "y": [2.0, 4.0, 6.0, 6.0, 4.0, 2.0],
        }
    )
    for expression in (
        "ZScore(x)",
        "Delay(x,1)",
        "Delta(x,1)",
        "Mean(x,2)",
        "StdDev(x,2)",
        "Correlation(x,y,2)",
        "Clip(x,1,2)",
    ):
        result = evaluate_factor_expression(
            frame.assign(available_at="2024-01-03T20:00:00Z"),
            expression,
            feature_names={"x", "y"},
            as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC),
        )
        assert set(result.columns) == {"date", "ticker", "score", "available_at"}
    with pytest.raises(ValueError, match="no finite scores"):
        evaluate_factor_expression(
            frame.assign(available_at="2024-01-03T20:00:00Z"),
            "Div(x,0)",
            feature_names={"x"},
            as_of_time=datetime(2024, 1, 3, 21, tzinfo=UTC),
        )
