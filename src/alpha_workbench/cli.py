"""Command-line entry points for reproducible offline demonstrations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .backtest import backtest_long_short
from .data import FrozenCSVMarketDataProvider, load_factors, parse_as_of
from .graph import SupplyChainGraph


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    as_of = parse_as_of(args.as_of)
    if args.command == "backtest":
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
    graph = SupplyChainGraph.from_json(args.edges)
    scenario_result = graph.scenario(args.shock, args.severity, as_of)
    print(json.dumps(scenario_result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
