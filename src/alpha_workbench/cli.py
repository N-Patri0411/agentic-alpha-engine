"""Command-line entry points for reproducible offline demonstrations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .adapters import (
    AlphaVantageDailyAdapter,
    OfficialEarningsEvidenceAdapter,
    OfficialInvestorRelationsAdapter,
    SecFilingAdapter,
    TavilyDiscoverySearchBackend,
    WebDiscoveryAdapter,
    WebFetchPolicy,
    WebPageContentAdapter,
    load_source_catalog,
)
from .agents import FilingExtractionRequest, build_extraction_agent
from .backtest import backtest_long_short
from .data import FrozenCSVMarketDataProvider, load_factors, parse_as_of
from .evidence.contracts import TextEvidence
from .evidence.initial_source_run import InitialSemiconductorSourceRun
from .evidence.ledger import DuckDBEvidenceLedger
from .evidence.runtime import EvidenceIntakeService
from .graph import SupplyChainGraph
from .graph_registry import EntityRegistry, RippleRiskScorer
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
    collect = commands.add_parser(
        "collect-initial-sources",
        help="collect bounded public evidence from every initial source family",
    )
    collect.add_argument(
        "--run-id",
        default=None,
        help="optional receipt identifier; default is a UTC timestamp",
    )
    collect.add_argument("--preview-limit", type=int, default=24)
    collect.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/private/evidence.duckdb"),
        help="ignored local DuckDB evidence-ledger path",
    )
    enrich = commands.add_parser(
        "enrich-web-discovery",
        help="fetch full text from allow-listed Tavily discovery results",
    )
    enrich.add_argument("--discovery-run", required=True)
    enrich.add_argument("--run-id", default=None)
    enrich.add_argument("--limit", type=int, default=8)
    enrich.add_argument("--preview-limit", type=int, default=16)
    enrich.add_argument(
        "--ledger", type=Path, default=Path("data/private/evidence.duckdb")
    )
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
    if args.command == "enrich-web-discovery":
        if args.limit < 1 or args.limit > 12:
            raise ValueError("limit must be between 1 and 12")
        run_id = args.run_id or f"web-content-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
        ledger = DuckDBEvidenceLedger(ledger_path)
        try:
            registry = EntityRegistry.from_json(
                root / "data" / "entities" / "semiconductor_v1.json"
            )
            policy = WebFetchPolicy.from_json(
                root / "data" / "source_catalog" / "web_fetch_allowlist_v1.json"
            )
            adapter = WebPageContentAdapter(root / "data" / "cache" / "web", policy)
            intake = EvidenceIntakeService(ledger, {adapter.name: adapter})
            aliases = {entity.entity_id: entity.aliases for entity in registry.entities}
            candidates = ledger.observations_for_run(
                args.discovery_run, source_adapter="web_discovery"
            )
            allowed = [
                candidate
                for candidate in candidates
                if policy.allows(candidate.document.source_url)
            ][: args.limit]
            receipts = [
                intake.collect(
                    adapter_name=adapter.name,
                    run_id=run_id,
                    query={
                        "candidate": candidate.model_dump(mode="json"),
                        "entity_aliases": aliases,
                        "max_passages": 2,
                        "run_id": run_id,
                    },
                )
                for candidate in allowed
            ]
            observations = ledger.observations_for_run(run_id, source_adapter=adapter.name)
            web_report = {
                "run_id": run_id,
                "candidate_count": len(candidates),
                "allow_list_eligible_count": len(allowed),
                "receipts": [receipt.model_dump(mode="json") for receipt in receipts],
                "previews": [
                    {
                        "issuer": observation.document.issuer_entity_id,
                        "url": observation.document.source_url,
                        "mentioned_entities": observation.mentioned_entity_ids,
                        "text": observation.payload.text[:400],
                    }
                    for observation in observations[: args.preview_limit]
                    if isinstance(observation.payload, TextEvidence)
                ],
            }
        finally:
            ledger.close()
        print(json.dumps(web_report, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "collect-initial-sources":
        run_id = args.run_id or f"initial-source-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
        ledger = DuckDBEvidenceLedger(ledger_path)
        try:
            source_run = InitialSemiconductorSourceRun(
                ledger=ledger,
                registry=EntityRegistry.from_json(
                    root / "data" / "entities" / "semiconductor_v1.json"
                ),
                catalog=load_source_catalog(
                    root / "data" / "source_catalog" / "semiconductor_primary_sources_v1.json"
                ),
                sec_filings=SecFilingAdapter(root / "data" / "cache" / "sec"),
                investor_relations=OfficialInvestorRelationsAdapter(root / "data" / "cache" / "ir"),
                earnings=OfficialEarningsEvidenceAdapter(),
                web_discovery=WebDiscoveryAdapter(
                    search_backend=TavilyDiscoverySearchBackend()
                ),
                market_data=AlphaVantageDailyAdapter(),
            )
            source_report = source_run.collect(run_id=run_id, preview_limit=args.preview_limit)
        finally:
            ledger.close()
        print(json.dumps(source_report.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
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
