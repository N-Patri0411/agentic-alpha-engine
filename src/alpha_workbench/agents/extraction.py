"""The composed Extraction Agent: source snapshot to validated draft evidence."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..adapters import SecFilingAdapter
from ..adapters.base import SourceSnapshot
from ..extraction import (
    DocumentPassage,
    EdgeProposal,
    EvidenceProposalExtractor,
    EvidenceValidationReport,
    EvidenceValidator,
    FilingSectionSelector,
    NoEdgeProposal,
)
from ..llm.models import LLMClient


class FilingExtractionRequest(BaseModel):
    cik: str = Field(min_length=1)
    known_entities: set[str] = Field(min_length=2)
    forms: list[str] = Field(default_factory=lambda: ["10-K", "20-F"])
    max_passages: int = Field(default=1, ge=1, le=5)


class FilingExtractionReport(BaseModel):
    filings: list[dict[str, object]]
    snapshot: SourceSnapshot
    passages: list[DocumentPassage]
    outcomes: list[EdgeProposal | NoEdgeProposal]
    validations: list[EvidenceValidationReport]


class ExtractionAgent:
    """Draft-only agent. It cannot publish a graph edge or execute a trade."""

    name = "extraction"

    def __init__(
        self,
        sec_filings: SecFilingAdapter,
        selector: FilingSectionSelector,
        extractor: EvidenceProposalExtractor,
        validator: EvidenceValidator,
        cache_dir: Path,
    ) -> None:
        self._sec_filings = sec_filings
        self._selector = selector
        self._extractor = extractor
        self._validator = validator
        self._cache_dir = cache_dir

    def run_filing(self, request: FilingExtractionRequest) -> FilingExtractionReport:
        filings = self._sec_filings.discover({"cik": request.cik, "forms": request.forms})
        if not filings:
            raise RuntimeError("no selected SEC filings found")
        snapshot = self._sec_filings.fetch(str(filings[0]["source_url"]))
        cached_html = self._cache_dir / f"{snapshot.content_sha256}.html"
        passages = self._selector.select(cached_html, snapshot, max_passages=request.max_passages)
        outcomes: list[EdgeProposal | NoEdgeProposal] = []
        validations: list[EvidenceValidationReport] = []
        for passage in passages:
            outcome = self._extractor.extract(passage)
            outcomes.append(outcome)
            if isinstance(outcome, EdgeProposal):
                validations.append(self._validator.validate(outcome))
        return FilingExtractionReport(
            filings=filings,
            snapshot=snapshot,
            passages=passages,
            outcomes=outcomes,
            validations=validations,
        )


def build_extraction_agent(
    *, cache_dir: Path, llm: LLMClient, known_entities: set[str]
) -> ExtractionAgent:
    """Composition root; callers choose the injected model and source clients."""

    return ExtractionAgent(
        SecFilingAdapter(cache_dir),
        FilingSectionSelector(),
        EvidenceProposalExtractor(llm, known_entities),
        EvidenceValidator(known_entities),
        cache_dir,
    )
