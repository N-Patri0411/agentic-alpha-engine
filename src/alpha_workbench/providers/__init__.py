"""Provider-neutral financial data adapters and contracts."""

from .contracts import (
    CalendarSession,
    CorporateAction,
    CoverageReport,
    DataChronology,
    EvidenceDocument,
    FxRate,
    HistoricalBar,
    IdentifierMapping,
    InstrumentRecord,
    ProviderBudget,
    ProviderCapability,
    ProviderProvenance,
)
from .protocols import ProviderAdapter
from .registry import ProviderRegistry, build_provider

__all__ = [
    "CalendarSession",
    "CorporateAction",
    "CoverageReport",
    "DataChronology",
    "EvidenceDocument",
    "FxRate",
    "HistoricalBar",
    "IdentifierMapping",
    "InstrumentRecord",
    "ProviderAdapter",
    "ProviderBudget",
    "ProviderCapability",
    "ProviderProvenance",
    "ProviderRegistry",
    "build_provider",
]
