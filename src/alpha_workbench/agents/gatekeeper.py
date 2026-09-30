"""Deterministic quality gate for paper-research backtest reports."""

from __future__ import annotations

import json
import math
from time import perf_counter
from typing import Literal

from ..models import BacktestReport
from .base import SkeletonAgent
from .contracts import AgentRequest, AgentResult, GateDecision

DecisionStatus = Literal["accepted", "rejected", "needs_review"]
AgentStatus = Literal["completed", "paused", "failed"]


class GatekeeperAgent(SkeletonAgent):
    """Apply a reproducible policy; a single in-sample report never passes."""

    name = "gatekeeper"

    def __init__(self, *, min_periods: int = 20, max_drawdown: float = -0.25,
                 require_positive_oos_return: bool = True) -> None:
        if min_periods < 1:
            raise ValueError("min_periods must be at least one")
        if max_drawdown > 0:
            raise ValueError("max_drawdown must be zero or negative")
        self.min_periods = min_periods
        self.max_drawdown = max_drawdown
        self.require_positive_oos_return = require_positive_oos_return

    def decide(self, candidate_id: str, report: BacktestReport, *,
               baseline_report: BacktestReport | None = None,
               out_of_sample_report: BacktestReport | None = None) -> GateDecision:
        if not candidate_id:
            raise ValueError("candidate_id cannot be empty")
        failures: list[str] = []
        review: list[str] = []
        if report.periods < self.min_periods:
            failures.append(
                f"insufficient historical periods: {report.periods} < {self.min_periods}"
            )
        if not math.isfinite(report.transaction_cost_bps) or report.transaction_cost_bps <= 0:
            failures.append("transaction costs must be present and greater than zero")
        if not math.isfinite(report.max_drawdown) or report.max_drawdown < self.max_drawdown:
            failures.append(
                f"maximum drawdown {report.max_drawdown!r} breaches limit {self.max_drawdown}"
            )
        if baseline_report is None:
            review.append("baseline comparison evidence is missing")
        elif report.net_return <= baseline_report.net_return:
            failures.append("candidate net return does not exceed the baseline")
        if out_of_sample_report is None:
            review.append("out-of-sample evidence is missing")
        else:
            if out_of_sample_report.periods < self.min_periods:
                failures.append(
                    "out-of-sample evidence has too few periods: "
                    f"{out_of_sample_report.periods} < {self.min_periods}"
                )
            if out_of_sample_report.transaction_cost_bps <= 0:
                failures.append("out-of-sample report does not include positive costs")
            if out_of_sample_report.max_drawdown < self.max_drawdown:
                failures.append("out-of-sample drawdown breaches the configured limit")
            if self.require_positive_oos_return and out_of_sample_report.net_return <= 0:
                failures.append("out-of-sample net return is not positive")
        reasons = [*failures, *review]
        status: DecisionStatus
        if failures:
            status = "rejected"
        elif review:
            status = "needs_review"
        else:
            status = "accepted"
            reasons.append(
                "all configured historical, cost, drawdown, baseline, and "
                "out-of-sample checks passed"
            )
        return GateDecision(candidate_id=candidate_id, decision=status, reasons=reasons)

    evaluate = decide

    def run(self, request: AgentRequest) -> AgentResult:
        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        if not request.payload:
            return super().run(request)
        started = perf_counter()
        try:
            payload = request.payload
            report = BacktestReport.model_validate(payload["report"])
            baseline = (BacktestReport.model_validate(payload["baseline_report"])
                        if payload.get("baseline_report") is not None else None)
            oos = (BacktestReport.model_validate(payload["out_of_sample_report"])
                   if payload.get("out_of_sample_report") is not None else None)
            decision = self.decide(str(payload["candidate_id"]), report,
                                   baseline_report=baseline, out_of_sample_report=oos)
            status: AgentStatus = "completed"
            message = json.dumps(decision.model_dump(mode="json"), sort_keys=True)
        except (KeyError, TypeError, ValueError) as exc:
            status, message = "failed", f"gate evaluation failed: {exc}"
        return AgentResult(run_id=request.run_id, agent=self.name, status=status, message=message,
                           latency_ms=int((perf_counter() - started) * 1000))
