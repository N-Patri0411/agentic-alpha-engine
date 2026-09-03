from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.adapters.source_catalog import load_source_catalog
from alpha_workbench.evidence import EvidenceObservation, MarketBar, SourceDocument, TextEvidence
from alpha_workbench.evidence.contracts import ExtractionProvenance
from alpha_workbench.evidence.initial_source_run import InitialSemiconductorSourceRun
from alpha_workbench.evidence.ledger import DuckDBEvidenceLedger
from alpha_workbench.graph_registry import EntityRegistry

NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)


class _FakeAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        if self.name == "official_investor_relations":
            sources = query["sources"]
            assert isinstance(sources, list)
            return [self._observation(str(source.issuer_entity_id)) for source in sources]
        if self.name == "official_earnings_evidence":
            documents = query["documents"]
            assert isinstance(documents, list)
            return [
                self._observation(str(document["issuer_entity_id"]))
                for document in documents
                if isinstance(document, dict)
            ]
        return [self._observation(str(query["issuer_entity_id"]))]

    def _observation(self, issuer: str) -> EvidenceObservation:
        digest = hashlib.sha256(f"{self.name}:{issuer}".encode()).hexdigest()
        kind = "market_data" if self.name == "alpha_vantage_daily" else "web_discovery"
        tier = "market_data" if kind == "market_data" else "discovery"
        document = SourceDocument(
            source_kind=kind,
            source_tier=tier,
            source_adapter=self.name,
            source_url=f"https://fixture.example.test/{self.name}/{issuer}",
            content_sha256=digest,
            issuer_entity_id=issuer,
            observed_at=NOW,
            available_at=NOW,
            retrieved_at=NOW,
            usage_note="fixture source",
        )
        if kind == "market_data":
            payload = MarketBar(
                symbol=issuer,
                bar_start=NOW,
                bar_end=datetime(2026, 9, 3, 12, tzinfo=UTC),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
            )
        else:
            payload = TextEvidence(
                text="Official fixture relationship evidence.",
                exact_quote="Official fixture relationship evidence.",
                character_start=0,
                character_end=39,
            )
        return EvidenceObservation(
            idempotency_key=f"{self.name}:{issuer}",
            document=document,
            mentioned_entity_ids=(issuer,),
            payload=payload,
            extraction=ExtractionProvenance(
                extractor_name=self.name, extractor_version="fixture", run_id="fixture"
            ),
        )


class _FakeSecAdapter(_FakeAdapter):
    def __init__(self) -> None:
        super().__init__("sec_filings")

    def discover(self, query: dict[str, object]) -> list[dict[str, object]]:
        if not query.get("include_exhibits"):
            return []
        return [
            {
                "document_kind": "exhibit_99",
                "form": "8-K",
                "filing_date": "2026-09-01",
                "source_url": "https://www.sec.gov/Archives/fixture-ex99.htm",
                "accession_number": "0000-00-000000",
            }
        ]


def test_initial_source_run_collects_every_configured_family(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")
    try:
        report = InitialSemiconductorSourceRun(
            ledger=ledger,
            registry=EntityRegistry.from_json(root / "data/entities/semiconductor_v1.json"),
            catalog=load_source_catalog(
                root / "data/source_catalog/semiconductor_primary_sources_v1.json"
            ),
            sec_filings=_FakeSecAdapter(),  # type: ignore[arg-type]
            investor_relations=_FakeAdapter("official_investor_relations"),  # type: ignore[arg-type]
            earnings=_FakeAdapter("official_earnings_evidence"),  # type: ignore[arg-type]
            web_discovery=_FakeAdapter("web_discovery"),  # type: ignore[arg-type]
            market_data=_FakeAdapter("alpha_vantage_daily"),  # type: ignore[arg-type]
        ).collect(run_id="initial-fixture-run")
    finally:
        ledger.close()

    assert report.observation_count == 28
    assert len(report.receipts) == 28
    assert {receipt.adapter_name for receipt in report.receipts} == {
        "sec_filings",
        "official_earnings_evidence",
        "official_investor_relations",
        "web_discovery",
        "alpha_vantage_daily",
    }
    assert all(receipt.status == "completed" for receipt in report.receipts)
