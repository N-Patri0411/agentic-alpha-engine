"""Command-line entry points for reproducible offline demonstrations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .a2a import DuckDBMessageBus
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
from .agents.extraction_graph_workflow import ExtractionGraphWorkflow
from .agents.graph_adjudicator import GraphAdjudicatorAgent
from .backtest import backtest_long_short
from .candidate_discovery import (
    observation_to_passage,
    select_candidate_discovery_observations,
)
from .candidate_graph import CandidateGraphBuilder
from .data import FrozenCSVMarketDataProvider, load_factors, parse_as_of
from .evidence.contracts import TextEvidence
from .evidence.initial_source_run import InitialSemiconductorSourceRun
from .evidence.ledger import DuckDBEvidenceLedger
from .evidence.runtime import EvidenceIntakeService
from .extraction import OpenWorldRelationshipExtractor
from .graph import SupplyChainGraph
from .graph_build import current_utc, select_graph_build_observations
from .graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot, RippleRiskScorer
from .graph_visualizer import render_graph_html
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
    discover = commands.add_parser(
        "discover-web",
        help="run one bounded Tavily discovery query for an approved entity",
    )
    discover.add_argument("--issuer", required=True)
    discover.add_argument("--query", required=True)
    discover.add_argument("--run-id", default=None)
    discover.add_argument("--max-results", type=int, default=5)
    discover.add_argument(
        "--ledger", type=Path, default=Path("data/private/evidence.duckdb")
    )
    visualize = commands.add_parser(
        "visualize-graph", help="render a reviewed snapshot into a local HTML graph"
    )
    visualize.add_argument("--snapshot", type=Path, required=True)
    visualize.add_argument(
        "--registry", type=Path, default=Path("data/entities/semiconductor_v1.json")
    )
    visualize.add_argument(
        "--output", type=Path, default=Path("reports/semiconductor-graph.html")
    )
    graph_build = commands.add_parser(
        "build-graph-from-evidence",
        help="run bounded Extraction-to-Adjudication over official pair-specific evidence",
    )
    graph_build.add_argument("--evidence-run", required=True)
    graph_build.add_argument("--current-snapshot", type=Path, required=True)
    graph_build.add_argument("--snapshot-id", required=True)
    graph_build.add_argument("--snapshot-output", type=Path, required=True)
    graph_build.add_argument("--run-id", required=True)
    graph_build.add_argument("--max-observations", type=int, default=5)
    graph_build.add_argument(
        "--ledger", type=Path, default=Path("data/private/evidence.duckdb")
    )
    graph_build.add_argument(
        "--message-bus", type=Path, default=Path("data/private/graph_build_messages.duckdb")
    )
    candidate_graph = commands.add_parser(
        "discover-candidate-graph",
        help="discover one-hop candidate entities from bounded official evidence",
    )
    candidate_graph.add_argument("--evidence-run", required=True)
    candidate_graph.add_argument("--run-id", required=True)
    candidate_graph.add_argument("--output", type=Path, required=True)
    candidate_graph.add_argument("--max-observations", type=int, default=5)
    candidate_graph.add_argument(
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
    if args.command == "discover-candidate-graph":
        ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
        output_path = args.output if args.output.is_absolute() else root / args.output
        if output_path.exists():
            raise ValueError("candidate graph output already exists; choose a new path")
        registry = EntityRegistry.from_json(root / "data" / "entities" / "semiconductor_v1.json")
        ledger = DuckDBEvidenceLedger(ledger_path)
        try:
            observations = ledger.observations_for_run(args.evidence_run)
            candidate_selected, candidate_selection = select_candidate_discovery_observations(
                observations=observations,
                maximum_observations=args.max_observations,
            )
        finally:
            ledger.close()
        candidate_aliases = {
            entity.entity_id: (entity.legal_name, entity.entity_id, *entity.aliases)
            for entity in registry.entities
        }
        extractor = OpenWorldRelationshipExtractor(
            create_llm(load_model_config(root / "config" / "models.yaml", "extraction")),
            candidate_aliases,
        )
        relationships = []
        for observation in candidate_selected:
            candidate_result = extractor.extract(
                observation_to_passage(observation),
                available_at=observation.document.available_at.isoformat(),
            )
            relationships.extend(candidate_result.relationships)
        candidate_graph = CandidateGraphBuilder(registry).build(relationships)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            candidate_graph.model_dump_json(indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "selection": candidate_selection.model_dump(mode="json"),
                    "candidate_node_count": len(candidate_graph.nodes),
                    "candidate_edge_count": len(candidate_graph.edges),
                    "ignored_relationship_count": candidate_graph.ignored_relationship_count,
                    "output": str(output_path),
                    "warning": (
                        "Candidate evidence only: this file cannot update a reviewed "
                        "snapshot or be scored by RippleRiskScorer."
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "build-graph-from-evidence":
        ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
        snapshot_path = (
            args.current_snapshot
            if args.current_snapshot.is_absolute()
            else root / args.current_snapshot
        )
        output_path = args.snapshot_output
        if not output_path.is_absolute():
            output_path = root / output_path
        bus_path = args.message_bus if args.message_bus.is_absolute() else root / args.message_bus
        registry = EntityRegistry.from_json(root / "data" / "entities" / "semiconductor_v1.json")
        snapshot = GraphSnapshot.from_json(snapshot_path)
        ledger = DuckDBEvidenceLedger(ledger_path)
        try:
            observations = ledger.observations_for_run(args.evidence_run)
            selected, selection = select_graph_build_observations(
                observations=observations,
                current_snapshot=snapshot,
                maximum_observations=args.max_observations,
            )
        finally:
            ledger.close()
        extraction = build_extraction_agent(
            cache_dir=root / "data" / "cache" / "sec",
            llm=create_llm(load_model_config(root / "config" / "models.yaml", "extraction")),
            known_entities=registry.entity_ids,
        )
        adjudicator = GraphAdjudicatorAgent(
            create_llm(load_model_config(root / "config" / "models.yaml", "graph_adjudicator")),
            registry,
            GraphPublisher(registry),
        )
        workflow = ExtractionGraphWorkflow(DuckDBMessageBus(bus_path), extraction, adjudicator)
        as_of_time = current_utc()
        extraction_message = workflow.enqueue_extraction(
            trace_id=f"graph-build:{args.run_id}",
            run_id=args.run_id,
            observations=selected,
            known_entities=registry.entity_ids,
            as_of_time=as_of_time,
        )
        graph_message = workflow.process_extraction(extraction_message)
        if graph_message is None:
            print(
                json.dumps(
                    {
                        "run_id": args.run_id,
                        "selection": selection.model_dump(mode="json"),
                        "status": "no_validated_proposals",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        report = workflow.process_graph(
            graph_message,
            current_snapshot=snapshot,
            next_snapshot_id=args.snapshot_id,
            snapshot_path=output_path,
        )
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "selection": selection.model_dump(mode="json"),
                    "source_urls": [item.document.source_url for item in selected],
                    "graph_adjudication": report.model_dump(mode="json"),
                    "snapshot_output": str(output_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "visualize-graph":
        snapshot_path = args.snapshot if args.snapshot.is_absolute() else root / args.snapshot
        registry_path = args.registry if args.registry.is_absolute() else root / args.registry
        output_path = args.output if args.output.is_absolute() else root / args.output
        visualization_receipt = render_graph_html(
            registry=EntityRegistry.from_json(registry_path),
            snapshot=GraphSnapshot.from_json(snapshot_path),
            output_path=output_path,
        )
        print(json.dumps(visualization_receipt.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0
    if args.command == "discover-web":
        if args.max_results < 1 or args.max_results > 10:
            raise ValueError("max-results must be between 1 and 10")
        run_id = args.run_id or f"web-discovery-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        ledger_path = args.ledger if args.ledger.is_absolute() else root / args.ledger
        ledger = DuckDBEvidenceLedger(ledger_path)
        try:
            registry = EntityRegistry.from_json(
                root / "data" / "entities" / "semiconductor_v1.json"
            )
            if args.issuer not in registry.entity_ids:
                raise ValueError("issuer must be an approved entity ID")
            backend = TavilyDiscoverySearchBackend(max_results=args.max_results)
            discovery_adapter = WebDiscoveryAdapter(search_backend=backend)
            receipt = EvidenceIntakeService(
                ledger, {discovery_adapter.name: discovery_adapter}
            ).collect(
                adapter_name=discovery_adapter.name,
                run_id=run_id,
                query={"issuer_entity_id": args.issuer, "query": args.query, "run_id": run_id},
            )
            observations = ledger.observations_for_run(
                run_id, source_adapter=discovery_adapter.name
            )
            discovery_report = {
                "run_id": run_id,
                "receipt": receipt.model_dump(mode="json"),
                "results": [
                    {
                        "url": observation.document.source_url,
                        "title": observation.document.title,
                        "summary": observation.payload.text[:400],
                    }
                    for observation in observations
                    if isinstance(observation.payload, TextEvidence)
                ],
            }
        finally:
            ledger.close()
        print(json.dumps(discovery_report, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "enrich-web-discovery":
        if args.limit < 1 or args.limit > 32:
            raise ValueError("limit must be between 1 and 32")
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
            content_adapter = WebPageContentAdapter(root / "data" / "cache" / "web", policy)
            intake = EvidenceIntakeService(ledger, {content_adapter.name: content_adapter})
            entity_aliases = {
                entity.entity_id: entity.aliases for entity in registry.entities
            }
            candidates = ledger.observations_for_run(
                args.discovery_run, source_adapter="web_discovery"
            )
            allowed = []
            seen_urls: set[str] = set()
            for candidate in candidates:
                url = candidate.document.source_url
                if not policy.allows(url) or url in seen_urls:
                    continue
                seen_urls.add(url)
                allowed.append(candidate)
                if len(allowed) == args.limit:
                    break
            receipts = [
                intake.collect(
                    adapter_name=content_adapter.name,
                    run_id=run_id,
                    query={
                        "candidate": candidate.model_dump(mode="json"),
                        "entity_aliases": entity_aliases,
                        "max_passages": 2,
                        "run_id": run_id,
                    },
                )
                for candidate in allowed
            ]
            observations = ledger.observations_for_run(run_id, source_adapter=content_adapter.name)
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
    filing_report = agent.run_filing(
        FilingExtractionRequest(
            cik=args.cik,
            issuer_entity_id=args.issuer_entity,
            known_entities=entities,
            max_passages=args.max_passages,
        )
    )
    print(json.dumps(filing_report.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
