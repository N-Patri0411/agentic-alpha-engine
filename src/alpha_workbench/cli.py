"""Command-line entry points for reproducible offline demonstrations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .agents import FilingExtractionRequest, build_extraction_agent
from .backtest import backtest_long_short
from .data import FrozenCSVMarketDataProvider, load_factors, parse_as_of
from .graph import SupplyChainGraph
from .graph_registry import RippleRiskScorer
from .llm.models import create_llm, load_model_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpha-workbench")
    commands = parser.add_subparsers(dest="command", required=True)

    backtest = commands.add_parser("backtest", help="run a frozen-data paper backtest")
    backtest.add_argument("--prices", type=Path, required=True)
    backtest.add_argument("--factors", type=Path, required=True)
    backtest.add_argument("--as-of", required=True, help="timezone-aware ISO timestamp")
    backtest.add_argument("--cost-bps", type=float, default=5.0)
    backtest.add_argument("--trial-count", type=int, default=1)

    scenario = commands.add_parser(
        "scenario", help="run a deterministic supply-chain shock scenario"
    )
    scenario.add_argument("--edges", type=Path, required=True)
    scenario.add_argument("--shock", required=True)
    scenario.add_argument("--severity", type=float, required=True)
    scenario.add_argument("--as-of", required=True, help="timezone-aware ISO timestamp")
    ripple = commands.add_parser(
        "ripple-score", help="replay a reviewed immutable graph snapshot"
    )
    ripple.add_argument("--snapshot", type=Path, required=True)
    ripple.add_argument("--shock", required=True)
    ripple.add_argument("--severity", type=float, required=True)
    ripple.add_argument("--as-of", required=True, help="timezone-aware ISO timestamp")
    ripple.add_argument("--max-hops", type=int, default=3)
    extract = commands.add_parser("extract-sec", help="run one bounded SEC-to-proposal extraction")
    extract.add_argument("--cik", required=True)
    extract.add_argument(
        "--issuer-entity",
        help="approved entity ID represented by the filing issuer (for example NVDA)",
    )
    extract.add_argument("--entities", nargs="+", required=True)
    extract.add_argument("--max-passages", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "backtest":
        as_of = parse_as_of(args.as_of)
        prices = FrozenCSVMarketDataProvider(args.prices).load_prices(as_of)
        factors = load_factors(args.factors, as_of)
        backtest_result = backtest_long_short(
            prices,
            factors,
            as_of_time=as_of,
            transaction_cost_bps=args.cost_bps,
            trial_count=args.trial_count,
        )
        print(json.dumps(backtest_result.report.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    if args.command == "scenario":
        as_of = parse_as_of(args.as_of)
        graph = SupplyChainGraph.from_json(args.edges)
        scenario_result = graph.scenario(args.shock, args.severity, as_of)
        print(json.dumps(scenario_result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    if args.command == "ripple-score":
        result = RippleRiskScorer.from_json(args.snapshot).score(
            shock_entity_id=args.shock,
            severity=args.severity,
            as_of_time=parse_as_of(args.as_of),
            max_hops=args.max_hops,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    root = Path.cwd()
    entities = set(args.entities)
    agent = build_extraction_agent(
        cache_dir=root / "data" / "cache" / "sec",
        llm=create_llm(load_model_config(root / "config" / "models.yaml", "extraction")),
        known_entities=entities,
    )
    report = agent.run_filing(
        FilingExtractionRequest(
            cik=args.cik,
            issuer_entity_id=args.issuer_entity,
            known_entities=entities,
            max_passages=args.max_passages,
        )
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
