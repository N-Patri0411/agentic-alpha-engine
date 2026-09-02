"""Immutable evidence records and the local append-only evidence ledger."""

from .contracts import (
    EventSignal,
    EvidenceObservation,
    EvidencePayload,
    EvidenceRunReceipt,
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
    "MarketBar",
    "SourceCatalogEntry",
    "SourceDocument",
    "StructuredFilingFact",
    "TextEvidence",
]
