"""Offline manual alpha pipeline orchestration and run receipts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import pandas as pd

from ..agents.alpha_generator import AlphaGeneratorAgent
from ..agents.backtester_agent import BacktesterAgent
from ..agents.contracts import AgentRequest, GateDecision
from ..agents.gatekeeper import GatekeeperAgent
from ..agents.portfolio import PortfolioOptimiserAgent
from ..data import market_bars_to_prices
from ..evidence.contracts import EvidenceObservation
from ..graph_features import graph_ripple_factors
from ..graph_registry import GraphSnapshot
from ..llm.models import FakeLLMClient, LLMClient
from ..models import BacktestReport
from .evaluator import evaluate_factor_expression


def run_offline_pipeline(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    feature_names: list[str],
    as_of_time: datetime,
    expression: str = "Rank(score)",
    run_id: str = "offline-manual",
    transaction_cost_bps: float = 5.0,
    llm: LLMClient | None = None,
    input_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run generation, DSL scoring, backtest, gate, and paper target creation."""

    generated = AlphaGeneratorAgent(
        llm or FakeLLMClient(
            {
                "candidates": [{
                    "id": "manual-1", "expression": expression, "rationale": "offline fixture"
                }]
            }
        )
    ).generate(
        AgentRequest(
            run_id=run_id,
            agent="alpha_generator",
            payload={
                "as_of_time": as_of_time,
                "features": [
                    {"name": name, "source_artifact_ids": [f"local:{name}"]}
                    for name in feature_names
                ],
            },
        )
    )
    if not generated.candidates:
        raise ValueError(f"alpha generation rejected formula: {generated.rejected}")
    candidate = generated.candidates[0]
    scored = evaluate_factor_expression(
        features,
        candidate.expression,
        feature_names=set(feature_names),
        as_of_time=as_of_time,
    )
    train, holdout = _chronological_split(scored)
    backtester = BacktesterAgent()
    evaluation = backtester.evaluate(
        prices,
        train if holdout is not None else scored,
        as_of_time=as_of_time,
        transaction_cost_bps=transaction_cost_bps,
    )
    backtest_payload = {
        "candidate": evaluation.candidate.report.model_dump(mode="json"),
        "baseline": evaluation.baseline.report.model_dump(mode="json"),
        "receipt_sha256": evaluation.receipt_sha256,
        "split": {
            "train_periods": int(train["date"].nunique()),
            "holdout_periods": int(holdout["date"].nunique()) if holdout is not None else 0,
            "chronological": True,
        },
    }
    if holdout is not None:
        oos = backtester.evaluate(
            prices,
            holdout,
            as_of_time=as_of_time,
            transaction_cost_bps=transaction_cost_bps,
        )
        backtest_payload["oos"] = {
            "candidate": oos.candidate.report.model_dump(mode="json"),
            "baseline": oos.baseline.report.model_dump(mode="json"),
            "receipt_sha256": oos.receipt_sha256,
        }
    gate = GatekeeperAgent()
    decision = _gate(gate, run_id, candidate, backtest_payload)
    paper = None
    if decision.decision == "accepted":
        paper = _paper(PortfolioOptimiserAgent(), run_id, scored, candidate, decision)
    receipt = {
        "run_id": run_id,
        "as_of_time": as_of_time.isoformat(),
        "candidate": candidate.model_dump(mode="json"),
        "formula": candidate.expression,
        "feature_names": feature_names,
        "scored_rows": len(scored),
        "backtest": backtest_payload,
        "gatekeeper": decision.model_dump(mode="json"),
        "paper_portfolio": paper,
        "limitations": [
            "Offline paper research demonstration; metrics do not establish alpha or performance."
        ],
        "input_hashes": input_hashes or {},
        "pipeline_version": "2026-09-30-alpha-pipeline-v1",
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(_stable(receipt), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return receipt


def run_graph_pipeline(
    snapshot: GraphSnapshot,
    observations: list[EvidenceObservation],
    *,
    shock_entity_id: str,
    as_of_time: datetime,
    source_run_ids: list[str],
    expression: str = "Neg(graph_ripple_risk)",
    run_id: str = "offline-graph-manual",
    transaction_cost_bps: float = 5.0,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Run the same pipeline from reviewed graph plus retained market bars."""

    price_snapshot = market_bars_to_prices(observations, as_of_time=as_of_time)
    prices = price_snapshot.prices
    if prices.empty:
        raise ValueError("no market bars were available at the requested as-of time")
    prices["date"] = pd.to_datetime(prices["date"])
    prices["available_at"] = pd.to_datetime(prices["available_at"], utc=True)
    prices = _prices_available_at_snapshot(prices, snapshot)
    if prices.empty:
        raise ValueError("no market bars occurred after the reviewed snapshot became available")
    dates = [
        pd.Timestamp(value)
        for value in prices.groupby("date", sort=True)["available_at"].max().tolist()
    ]
    tickers = sorted(prices["ticker"].astype(str).unique())
    features, graph_receipt = graph_ripple_factors(
        snapshot,
        dates=dates,
        tickers=tickers,
        shock_entity_id=shock_entity_id,
        as_of_time=as_of_time,
    )
    try:
        receipt = run_offline_pipeline(
            prices,
            features.rename(columns={"score": "graph_ripple_risk"}),
            feature_names=["graph_ripple_risk"],
            as_of_time=as_of_time,
            expression=expression,
            run_id=run_id,
            transaction_cost_bps=transaction_cost_bps,
            llm=llm,
            input_hashes={
                "graph_snapshot_sha256": snapshot.edges_sha256,
                "graph_feature_receipt_sha256": graph_receipt.receipt_sha256,
            },
        )
    except ValueError as error:
        if "next-period return" not in str(error):
            raise
        receipt = {
            "run_id": run_id,
            "as_of_time": as_of_time.isoformat(),
            "formula": expression,
            "scored_rows": len(features),
            "backtest": None,
            "gatekeeper": {
                "candidate_id": "unscored",
                "decision": "rejected",
                "reasons": [f"insufficient post-snapshot price history: {error}"],
            },
            "paper_portfolio": None,
            "limitations": ["No fabricated backtest was produced from insufficient history."],
            "input_hashes": {"graph_snapshot_sha256": snapshot.edges_sha256},
            "pipeline_version": "2026-09-30-alpha-pipeline-v1",
        }
    receipt["graph"] = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_sha256": snapshot.edges_sha256,
        "shock_entity_id": shock_entity_id,
        "feature_receipt": {
            "snapshot_id": graph_receipt.snapshot_id,
            "snapshot_sha256": graph_receipt.snapshot_sha256,
            "feature_name": graph_receipt.feature_name,
            "shock_entity_id": graph_receipt.shock_entity_id,
            "as_of_time": graph_receipt.as_of_time.isoformat(),
            "row_count": graph_receipt.row_count,
            "receipt_sha256": graph_receipt.receipt_sha256,
        },
        "market_observation_ids": price_snapshot.receipt.selected_observation_ids,
        "market_receipt": price_snapshot.receipt.model_dump(mode="json"),
        "source_run_ids": source_run_ids,
        "as_of_time": as_of_time.isoformat(),
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(_stable(receipt), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return receipt


def _prices_available_at_snapshot(
    prices: pd.DataFrame, snapshot: GraphSnapshot
) -> pd.DataFrame:
    snapshot_available_at = max(
        [snapshot.created_at]
        + [
            timestamp
            for edge in snapshot.edges
            for timestamp in (edge.evidence.filing_date, edge.review.reviewed_at)
        ]
    )
    return prices.loc[prices["available_at"] >= snapshot_available_at].reset_index(drop=True)


def _gate(
    agent: GatekeeperAgent, run_id: str, candidate: Any, backtest: dict[str, Any]
) -> GateDecision:
    if hasattr(agent, "decide"):
        result = agent.decide(
            candidate.id,
            BacktestReport.model_validate(backtest["candidate"]),
            baseline_report=BacktestReport.model_validate(backtest["baseline"]),
            out_of_sample_report=(
                BacktestReport.model_validate(backtest["oos"]["candidate"])
                if "oos" in backtest
                else None
            ),
        )
        return result
    raise TypeError("GatekeeperAgent must expose decide(candidate_id, report, baseline_report=...)")


def _chronological_split(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Return train and final-date holdout, only when both have 20 periods."""

    dates = sorted(pd.Timestamp(value) for value in scored["date"].dropna().unique())
    if len(dates) < 40:
        return scored, None
    holdout_count = max(20, int(len(dates) * 0.30 + 0.999999))
    cutoff = dates[-holdout_count]
    train = scored[scored["date"] < cutoff].copy()
    holdout = scored[scored["date"] >= cutoff].copy()
    if train["date"].nunique() < 20 or holdout["date"].nunique() < 20:
        return scored, None
    return train, holdout


def _paper(
    agent: PortfolioOptimiserAgent,
    run_id: str,
    scored: pd.DataFrame,
    candidate: Any,
    decision: GateDecision,
) -> dict[str, Any]:
    if hasattr(agent, "build_targets"):
        scores = scored.groupby("ticker", sort=False)["score"].last().to_dict()
        result = agent.build_targets(decision, scores)
        return result.model_dump(mode="json")
    raise TypeError("PortfolioOptimiserAgent must expose build_targets(decision, scores)")


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in {"generated_at"}}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value
