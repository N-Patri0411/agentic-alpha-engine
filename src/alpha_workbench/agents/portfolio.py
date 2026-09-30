"""Paper-only portfolio target construction (no broker or order path)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field

from .base import SkeletonAgent
from .contracts import AgentRequest, AgentResult, GateDecision

AgentStatus = Literal["completed", "paused", "failed"]


class PaperTarget(BaseModel):
    ticker: str = Field(min_length=1)
    weight: float


class PaperPortfolio(BaseModel):
    candidate_id: str
    targets: list[PaperTarget]
    status: str
    note: str


class PortfolioOptimiserAgent(SkeletonAgent):
    """Turn accepted scores into bounded, equal-weight paper targets."""

    name = "portfolio_optimiser"

    def build_targets(self, decision: GateDecision, scores: Mapping[str, float], *,
                      tickers_per_side: int = 1,
                      max_position_weight: float = 0.25) -> PaperPortfolio:
        if tickers_per_side < 1:
            raise ValueError("tickers_per_side must be at least one")
        if not 0 < max_position_weight <= 0.5:
            raise ValueError("max_position_weight must be in (0, 0.5]")
        if decision.decision != "accepted":
            return PaperPortfolio(candidate_id=decision.candidate_id, targets=[],
                                  status=decision.decision,
                                  note=("No paper targets created because the gate decision "
                                        "was not accepted."))
        clean = {str(ticker): float(score) for ticker, score in scores.items()
                 if str(ticker) and math.isfinite(float(score))}
        if len(clean) < 2 * tickers_per_side:
            raise ValueError("not enough finite signals for both paper long and short sides")
        ranked = sorted(clean.items(), key=lambda item: (-item[1], item[0]))
        longs, shorts = ranked[:tickers_per_side], ranked[-tickers_per_side:]
        side_weight = min(0.5 / tickers_per_side, max_position_weight)
        targets = [*(PaperTarget(ticker=ticker, weight=side_weight) for ticker, _ in longs),
                   *(PaperTarget(ticker=ticker, weight=-side_weight) for ticker, _ in shorts)]
        return PaperPortfolio(candidate_id=decision.candidate_id, targets=targets,
                              status="paper_only",
                              note=("Targets are research weights only; no broker or order "
                                    "path exists."))

    optimise = build_targets

    def run(self, request: AgentRequest) -> AgentResult:
        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        if not request.payload:
            return super().run(request)
        started = perf_counter()
        try:
            payload = request.payload
            decision = GateDecision.model_validate(payload["decision"])
            output = self.build_targets(decision, _scores(payload["scores"]),
                                        tickers_per_side=_as_int(
                                            payload.get("tickers_per_side", 1)),
                                        max_position_weight=float(
                                            _as_float(payload.get("max_position_weight", 0.25))))
            status: AgentStatus = "completed"
            message = json.dumps(output.model_dump(mode="json"), sort_keys=True)
        except (KeyError, TypeError, ValueError) as exc:
            status, message = "failed", f"paper portfolio construction failed: {exc}"
        return AgentResult(run_id=request.run_id, agent=self.name, status=status, message=message,
                           latency_ms=int((perf_counter() - started) * 1000))


def _scores(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise TypeError("scores must be a mapping of ticker to numeric score")
    converted: dict[str, float] = {}
    for ticker, score in value.items():
        if not isinstance(ticker, str) or not isinstance(score, (int, float)):
            raise TypeError("scores must be a mapping of ticker to numeric score")
        converted[ticker] = float(score)
    return converted


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("tickers_per_side must be an integer")
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("max_position_weight must be numeric")
    return float(value)
