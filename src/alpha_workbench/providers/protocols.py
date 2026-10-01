"""Public protocol implemented by all financial data providers."""

from __future__ import annotations

from typing import Protocol

from .contracts import (
    CorporateActionsResult,
    DiscoveryResult,
    EvidenceDocumentRequest,
    EvidenceDocumentsResult,
    ExchangeCalendarRequest,
    ExchangeCalendarResult,
    FundamentalsResult,
    FxRatesRequest,
    FxRatesResult,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    IdentifierMappingRequest,
    InstrumentQuery,
    MappingResult,
    ProviderBudget,
    ProviderCapability,
)


class ProviderAdapter(Protocol):
    """Provider-neutral interface. Unsupported methods return explicit coverage."""

    @property
    def capability(self) -> ProviderCapability: ...

    @property
    def budget(self) -> ProviderBudget: ...

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult: ...

    def map_identifier(self, request: IdentifierMappingRequest) -> MappingResult: ...

    def historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult: ...

    def fundamentals(self, request: InstrumentQuery) -> FundamentalsResult: ...

    def corporate_actions(self, request: HistoricalBarsRequest) -> CorporateActionsResult: ...

    def exchange_calendar(self, request: ExchangeCalendarRequest) -> ExchangeCalendarResult: ...

    def fx_rates(self, request: FxRatesRequest) -> FxRatesResult: ...

    def evidence_documents(self, request: EvidenceDocumentRequest) -> EvidenceDocumentsResult: ...
