"""A bounded agent wrapper around the deterministic paper backtest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from ..alpha.evaluator import evaluate_factor_expression
from ..backtest import BacktestResult, backtest_long_short
from ..data import parse_as_of
from .base import SkeletonAgent
from .contracts import AgentRequest, AgentResult


@dataclass(frozen=True)
class BacktestEvaluation:
    candidate: BacktestResult
    baseline: BacktestResult
    receipt_sha256: str


class BacktesterAgent(SkeletonAgent):
    """Evaluate one candidate and a transparent deterministic baseline.

    ``evaluate`` is the typed integration point for alpha generation.  ``run``
    additionally accepts JSON-compatible ``prices`` and ``factors`` rows for
    the A2A shell, while deliberately avoiding any model calls or side effects.
    """

    name = "backtester"

    def evaluate(
        self,
        prices: pd.DataFrame,
        factors: pd.DataFrame,
        *,
        as_of_time: datetime,
        baseline_factors: pd.DataFrame | None = None,
        tickers_per_side: int = 1,
        transaction_cost_bps: float = 5.0,
        trial_count: int = 1,
    ) -> BacktestEvaluation:
        as_of = parse_as_of(as_of_time)
        candidate = backtest_long_short(
            prices,
            factors,
            as_of_time=as_of,
            tickers_per_side=tickers_per_side,
            transaction_cost_bps=transaction_cost_bps,
            trial_count=trial_count,
        )
        baseline = (
            baseline_factors if baseline_factors is not None else _alphabetical_baseline(factors)
        )
        baseline_result = backtest_long_short(
            prices,
            baseline,
            as_of_time=as_of,
            tickers_per_side=tickers_per_side,
            transaction_cost_bps=transaction_cost_bps,
            trial_count=trial_count,
        )
        payload = {
            "as_of_time": as_of.isoformat(),
            "configuration": [tickers_per_side, transaction_cost_bps, trial_count],
            "candidate": _frame_digest(factors),
            "baseline": _frame_digest(baseline),
            "prices": _frame_digest(prices),
        }
        receipt = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return BacktestEvaluation(candidate, baseline_result, receipt)

    def evaluate_candidate_expression(
        self,
        prices: pd.DataFrame,
        features: pd.DataFrame,
        *,
        expression: str,
        feature_names: set[str] | list[str],
        as_of_time: datetime,
        **kwargs: object,
    ) -> BacktestEvaluation:
        """Parse one generated DSL formula and evaluate its scored factor frame."""

        factors = evaluate_factor_expression(
            features,
            expression,
            feature_names=feature_names,
            as_of_time=as_of_time,
        )
        return self.evaluate(prices, factors, as_of_time=as_of_time, **kwargs)  # type: ignore[arg-type]

    def run(self, request: AgentRequest) -> AgentResult:
        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        started = __import__("time").perf_counter()
        payload = request.payload
        if not payload:
            return super().run(request)
        try:
            prices = pd.DataFrame(payload["prices"])
            factors = pd.DataFrame(payload["factors"])
            result = self.evaluate(
                prices,
                factors,
                as_of_time=parse_as_of(str(payload["as_of_time"])),
                baseline_factors=(
                    pd.DataFrame(payload["baseline_factors"])
                    if payload.get("baseline_factors") is not None
                    else None
                ),
            )
            message = json.dumps(
                {
                    "receipt_sha256": result.receipt_sha256,
                    "candidate": result.candidate.report.model_dump(mode="json"),
                    "baseline": result.baseline.report.model_dump(mode="json"),
                    "net_return_delta": result.candidate.report.net_return
                    - result.baseline.report.net_return,
                    "limitations": [
                        "Diagnostics only; candidate outperformance is not evidence of alpha.",
                        "Baseline defaults to deterministic alphabetical ranking when omitted.",
                    ],
                },
                sort_keys=True,
            )
            status: Literal["completed", "failed"] = "completed"
        except (KeyError, TypeError, ValueError) as exc:
            message = f"backtest evaluation failed: {exc}"
            status = "failed"
        return AgentResult(
            run_id=request.run_id,
            agent=self.name,
            status=status,
            message=message,
            latency_ms=int((__import__("time").perf_counter() - started) * 1000),
        )

def _alphabetical_baseline(factors: pd.DataFrame) -> pd.DataFrame:
    baseline = factors[["date", "ticker", "available_at"]].copy()
    baseline["score"] = baseline["ticker"].astype(str).rank(method="dense", ascending=False)
    return baseline[["date", "ticker", "score", "available_at"]]


def _frame_digest(frame: pd.DataFrame) -> str:
    canonical = frame.sort_index(axis=1).sort_values(list(frame.columns)).to_json(
        orient="records", date_format="iso"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
