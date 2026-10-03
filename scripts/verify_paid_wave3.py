"""Bounded paid smoke test for real evidence -> extraction -> temporal graph policy.

This manual script makes exactly two extraction-model calls using two official
ASML/TSMC documents already present in the ignored local evidence ledger. It
does not collect network data or publish to the durable graph repository.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.agents.extraction import (
    ObservationExtractionRequest,
    build_extraction_agent,
)
from alpha_workbench.evidence import DuckDBEvidenceLedger, TextEvidence
from alpha_workbench.extraction import EdgeProposal
from alpha_workbench.graph_pipeline import GraphPipelineRequest, bootstrap_graph
from alpha_workbench.llm.models import create_llm, load_model_config
from alpha_workbench.product import InstrumentRef, UniverseSpec
from alpha_workbench.temporal_graph import InMemoryTemporalGraphRepository

OFFICIAL_URLS = {
    "https://www.asml.com/en/news/press-releases/2010/"
    "tsmc-to-take-delivery-of-an-asml-euv-lithography-system",
    "https://investor.tsmc.com/static/annualReports/2014/english/e_5_2.html",
}
ENTITY_IDS = ("AMAT", "AMD", "ASML", "GFS", "Hynix", "MU", "NVDA", "Samsung", "TSM", "UMC")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ledger_path = root / "data" / "private" / "evidence.duckdb"
    with DuckDBEvidenceLedger(ledger_path) as ledger:
        observations = [
            item
            for item in ledger.observations_as_of(datetime.now(UTC))
            if item.document.source_url in OFFICIAL_URLS and isinstance(item.payload, TextEvidence)
        ]
    selected = []
    seen_urls: set[str] = set()
    for observation in observations:
        if observation.document.source_url not in seen_urls:
            selected.append(observation)
            seen_urls.add(observation.document.source_url)
    if len(selected) != 2:
        raise RuntimeError(f"expected two official smoke observations, found {len(selected)}")

    llm = create_llm(load_model_config(root / "config" / "models.yaml", "extraction"))
    extraction = build_extraction_agent(
        cache_dir=root / "data" / "private" / "extraction-cache",
        llm=llm,
        known_entities=set(ENTITY_IDS),
    )
    report = extraction.run_observations(
        ObservationExtractionRequest(observations=selected, known_entities=set(ENTITY_IDS))
    )
    proposals = tuple(item for item in report.outcomes if isinstance(item, EdgeProposal))
    universe = UniverseSpec(
        universe_id="paid-wave3-smoke",
        workspace_id="paid-wave3-smoke",
        domain="semiconductors",
        instruments=tuple(
            InstrumentRef(
                instrument_id=f"SMOKE:{entity_id}",
                symbol=entity_id,
                exchange="SMOKE",
                currency="USD",
                entity_id=entity_id,
            )
            for entity_id in ENTITY_IDS
        ),
        selection_time=datetime.now(UTC),
        selection_mode="current",
        selection_method="bounded paid Wave 3 smoke test",
        target_count=10,
    )
    now = datetime.now(UTC)
    snapshot, pipeline_report = bootstrap_graph(
        GraphPipelineRequest(
            universe=universe,
            as_of_time=now,
            knowledge_time=now,
            observations=tuple(selected),
            validated_proposals=proposals,
            validation_reports=tuple(report.validations),
            trigger="bootstrap",
            request_id="paid-wave3-smoke",
        ),
        InMemoryTemporalGraphRepository(),
    )
    print(
        json.dumps(
            {
                "paid_model_calls": len(selected),
                "model_outcomes": [
                    {
                        "status": item.status,
                        "source": getattr(item, "source_entity_id", None),
                        "target": getattr(item, "target_entity_id", None),
                        "relationship_type": getattr(item, "relationship_type", None),
                    }
                    for item in report.outcomes
                ],
                "deterministic_validation": [item.verdict for item in report.validations],
                "snapshot_id": snapshot.snapshot_id,
                "visible_edges": len(snapshot.visible_edge_states()),
                "policy_decisions": [
                    {
                        "status": item.status,
                        "confidence": item.confidence,
                        "independent_sources": item.independent_sources,
                        "reason": item.reason,
                    }
                    for item in pipeline_report.decisions
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
