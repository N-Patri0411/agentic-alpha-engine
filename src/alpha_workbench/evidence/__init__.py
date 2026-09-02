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
from .runtime import EvidenceIntakeService, NightlyGraphConsolidator

__all__ = [
    "DuckDBEvidenceLedger",
    "EvidenceIntakeService",
    "EvidenceObservation",
    "EvidencePayload",
    "EvidenceRunReceipt",
    "EventSignal",
    "ExtractionProvenance",
    "MarketBar",
    "NightlyGraphConsolidator",
    "SourceCatalogEntry",
    "SourceDocument",
    "StructuredFilingFact",
    "TextEvidence",
]
