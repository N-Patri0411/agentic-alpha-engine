from datetime import UTC, datetime

from alpha_workbench.agents.contracts import GateDecision
from alpha_workbench.agents.gatekeeper import GatekeeperAgent
from alpha_workbench.agents.portfolio import PortfolioOptimiserAgent
from alpha_workbench.models import BacktestReport


def report(net_return: float, *, periods: int = 25) -> BacktestReport:
    return BacktestReport(
        as_of_time=datetime.now(UTC),
        periods=periods,
        mean_rank_ic=0.1,
        gross_return=net_return + 0.01,
        net_return=net_return,
        annualized_sharpe=1.0,
        max_drawdown=-0.1,
        average_turnover=0.1,
        transaction_cost_bps=5.0,
        trial_count=1,
        limitations=[],
    )


def test_gate_requires_baseline_and_out_of_sample_evidence() -> None:
    decision = GatekeeperAgent().decide("candidate", report(0.2))
    assert decision.decision == "needs_review"
    assert len(decision.reasons) == 2


def test_gate_accepts_only_when_all_evidence_passes() -> None:
    decision = GatekeeperAgent().decide(
        "candidate", report(0.2), baseline_report=report(0.1), out_of_sample_report=report(0.05)
    )
    assert decision.decision == "accepted"


def test_portfolio_never_creates_targets_for_unaccepted_decision() -> None:
    decision = GateDecision(candidate_id="candidate", decision="rejected", reasons=["bad"])
    output = PortfolioOptimiserAgent().build_targets(decision, {"AAA": 1, "BBB": -1})
    assert output.targets == []


def test_portfolio_creates_bounded_paper_long_short_targets() -> None:
    decision = GateDecision(candidate_id="candidate", decision="accepted", reasons=["ok"])
    output = PortfolioOptimiserAgent().build_targets(
        decision, {"AAA": 3, "BBB": 2, "CCC": 1, "DDD": 0}
    )
    assert [(target.ticker, target.weight) for target in output.targets] == [
        ("AAA", 0.25),
        ("DDD", -0.25),
    ]
