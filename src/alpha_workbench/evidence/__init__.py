"""Immutable evidence records and the local append-only evidence ledger."""

from .contracts import (
    EventSignal,
    EvidenceObservation,
    EvidencePayload,
    EvidenceRunReceipt,
    ExtractionProvenance,
    MarketBar,
    SourceCatalogEntry,
    SourceDocument,
    StructuredFilingFact,
    TextEvidence,
)
from .ledger import DuckDBEvidenceLedger

__all__ = [
    "DuckDBEvidenceLedger",
    "EvidenceObservation",
    "EvidencePayload",
    "EvidenceRunReceipt",
    "EventSignal",
    "ExtractionProvenance",
    "MarketBar",
    "SourceCatalogEntry",
    "SourceDocument",
    "StructuredFilingFact",
    "TextEvidence",
]
