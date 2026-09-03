"""Bounded collection of every initially planned semiconductor evidence family."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from ..adapters import (
    AlphaVantageDailyAdapter,
    OfficialEarningsEvidenceAdapter,
    OfficialInvestorRelationsAdapter,
    SecEarningsDocumentDiscoverer,
    SecFilingAdapter,
    WebDiscoveryAdapter,
)
from ..adapters.source_catalog import SourceCatalog
from ..graph_registry import EntityRegistry
from .contracts import EvidenceObservation, EvidenceRunReceipt, MarketBar, TextEvidence
from .ledger import DuckDBEvidenceLedger
from .runtime import EvidenceIntakeService


class EvidencePreview(BaseModel):
    source_kind: str
    source_tier: str
    issuer_entity_id: str
    title: str | None
    source_url: str
    available_at: datetime
    payload_type: str
    preview: str


class InitialSourceRunReport(BaseModel):
    run_id: str
    receipts: list[EvidenceRunReceipt]
    observation_count: int = Field(ge=0)
    previews: list[EvidencePreview]


class InitialSemiconductorSourceRun:
    """Coordinates source adapters; it never invokes LLMs or publishes graph edges."""

    def __init__(
        self,
        *,
        ledger: DuckDBEvidenceLedger,
        registry: EntityRegistry,
        catalog: SourceCatalog,
        sec_filings: SecFilingAdapter,
        investor_relations: OfficialInvestorRelationsAdapter,
        earnings: OfficialEarningsEvidenceAdapter,
        web_discovery: WebDiscoveryAdapter,
        market_data: AlphaVantageDailyAdapter,
    ) -> None:
        self._ledger = ledger
        self._registry = registry
        self._catalog = catalog
        self._earnings_discoverer = SecEarningsDocumentDiscoverer(sec_filings)
        self._intake = EvidenceIntakeService(
            ledger,
            {
                sec_filings.name: sec_filings,
                investor_relations.name: investor_relations,
                earnings.name: earnings,
                web_discovery.name: web_discovery,
                market_data.name: market_data,
            },
        )

    def collect(self, *, run_id: str, preview_limit: int = 24) -> InitialSourceRunReport:
        """Run the initial public-source family with explicit, small collection bounds."""

        receipts: list[EvidenceRunReceipt] = []
        cik_by_entity = {
            source.issuer_entity_id: source.cik
            for source in self._catalog.for_adapter("sec_filings")
            if source.cik
        }
        for entity in self._registry.entities:
            cik = cik_by_entity.get(entity.entity_id)
            if cik:
                receipts.append(
                    self._intake.collect(
                        adapter_name="sec_filings",
                        run_id=run_id,
                        query={
                            "cik": cik,
                            "issuer_entity_id": entity.entity_id,
                            "forms": ["10-K", "10-Q", "8-K", "20-F", "6-K"],
                            "max_filings": 1,
                            "max_passages": 1,
                            "include_exhibits": False,
                            "run_id": run_id,
                        },
                    )
                )
                try:
                    earnings_documents = self._earnings_discoverer.discover(
                        cik=cik,
                        issuer_entity_id=entity.entity_id,
                        max_documents=1,
                        max_filings_to_inspect=4,
                    )
                except Exception as error:
                    receipts.append(
                        self._intake.record_failure(
                            adapter_name="official_earnings_evidence", run_id=run_id, error=error
                        )
                    )
                    earnings_documents = []
                if earnings_documents:
                    receipts.append(
                        self._intake.collect(
                            adapter_name="official_earnings_evidence",
                            run_id=run_id,
                            query={
                                "documents": [
                                    document.model_dump(mode="json")
                                    for document in earnings_documents
                                ],
                                "max_windows_per_document": 1,
                            },
                        )
                    )
            if entity.ticker:
                receipts.append(
                    self._intake.collect(
                        adapter_name="alpha_vantage_daily",
                        run_id=run_id,
                        query={
                            "issuer_entity_id": entity.entity_id,
                            "symbol": entity.ticker,
                            "outputsize": "compact",
                            "run_id": run_id,
                        },
                    )
                )
            receipts.append(
                self._intake.collect(
                    adapter_name="web_discovery",
                    run_id=run_id,
                    query={
                        "issuer_entity_id": entity.entity_id,
                        "query": f"{entity.legal_name} semiconductor supply chain dependency",
                        "run_id": run_id,
                    },
                )
            )
        for source in self._catalog.for_adapter("investor_relations"):
            receipts.append(
                self._intake.collect(
                    adapter_name="official_investor_relations",
                    run_id=run_id,
                    query={"sources": [source], "max_linked_pages": 2, "run_id": run_id},
                )
            )
        observations_by_key = {
            observation.idempotency_key: observation
            for observation in self._ledger.observations_as_of(datetime.now(UTC))
        }
        run_keys = {
            key for receipt in receipts for key in receipt.observation_idempotency_keys
        }
        observations = [observations_by_key[key] for key in run_keys if key in observations_by_key]
        observations.sort(key=lambda observation: observation.document.retrieved_at)
        return InitialSourceRunReport(
            run_id=run_id,
            receipts=receipts,
            observation_count=len(observations),
            previews=[self._preview(observation) for observation in observations[-preview_limit:]],
        )

    @staticmethod
    def _preview(observation: EvidenceObservation) -> EvidencePreview:
        payload = observation.payload
        if isinstance(payload, TextEvidence):
            preview = payload.text[:280]
        elif isinstance(payload, MarketBar):
            preview = (
                f"{payload.symbol} close={payload.close} volume={payload.volume} "
                f"bar_end={payload.bar_end.isoformat()}"
            )
        else:
            preview = str(payload)[:280]
        document = observation.document
        return EvidencePreview(
            source_kind=document.source_kind,
            source_tier=document.source_tier,
            issuer_entity_id=document.issuer_entity_id,
            title=document.title,
            source_url=document.source_url,
            available_at=document.available_at,
            payload_type=payload.payload_type,
            preview=preview,
        )
