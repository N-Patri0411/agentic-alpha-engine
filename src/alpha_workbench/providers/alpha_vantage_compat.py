"""Migration bridge for the existing event-market Alpha Vantage adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from ..adapters.alpha_vantage import AlphaVantageDailyAdapter
from ..evidence.contracts import MarketBar
from .base import unsupported
from .contracts import (
    CapabilityName,
    CorporateActionsResult,
    CoverageReport,
    CoverageStatus,
    DataChronology,
    DiscoveryResult,
    EvidenceDocumentRequest,
    EvidenceDocumentsResult,
    ExchangeCalendarRequest,
    ExchangeCalendarResult,
    FundamentalsResult,
    FxRatesRequest,
    FxRatesResult,
    HistoricalBar,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    IdentifierMappingRequest,
    InstrumentQuery,
    MappingResult,
    ProviderBudget,
    ProviderCapability,
    ProviderProvenance,
)


class AlphaVantageCompatibilityAdapter:
    def __init__(
        self,
        *,
        adapter: AlphaVantageDailyAdapter | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        max_requests_per_minute: int = 5,
        max_requests_per_run: int = 100,
    ) -> None:
        self._adapter = adapter or AlphaVantageDailyAdapter(api_key=api_key, client=client)
        self._budget = ProviderBudget(
            max_requests_per_minute=max_requests_per_minute,
            max_requests_per_run=max_requests_per_run,
        )
        self._capability = ProviderCapability(
            provider_id="alpha_vantage_compat",
            display_name="Alpha Vantage (compatibility)",
            capabilities=("historical_bars",),
            markets=("US",),
            frequencies=("daily",),
            supports_point_in_time=False,
            rate_limit_per_minute=max_requests_per_minute,
            licensing_note="Legacy development adapter; no point-in-time availability guarantee.",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AlphaVantageCompatibilityAdapter:
        from .base import credential_from_env

        budget = config.get("budget", {})
        if not isinstance(budget, dict):
            raise ValueError("Alpha Vantage budget must be a mapping")
        return cls(
            api_key=credential_from_env(config, "ALPHAVANTAGE_API_KEY"),
            max_requests_per_minute=int(budget.get("max_requests_per_minute", 5)),
            max_requests_per_run=int(budget.get("max_requests_per_run", 100)),
        )

    @property
    def capability(self) -> ProviderCapability:
        return self._capability

    @property
    def budget(self) -> ProviderBudget:
        return self._budget

    def historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult:
        if request.interval != "daily":
            return HistoricalBarsResult(
                items=(),
                coverage=CoverageReport(
                    capability="historical_bars",
                    status="unsupported",
                    requested_count=1,
                    detail="legacy Alpha Vantage adapter supports daily bars only",
                ),
                provenance=self._provenance(),
                as_of_time=request.as_of_time,
            )
        observations = self._adapter.collect(
            {
                "issuer_entity_id": request.instrument.figi or request.instrument.symbol,
                "symbol": request.instrument.symbol,
                "outputsize": "full",
            }
        )
        bars: list[HistoricalBar] = []
        missing: list[str] = []
        for observation in observations:
            payload = observation.payload
            if not isinstance(payload, MarketBar):
                continue
            day = payload.bar_start.date()
            if day < request.start or day > request.end:
                continue
            if observation.document.available_at > request.as_of_time:
                missing.append(day.isoformat())
                continue
            bars.append(
                HistoricalBar(
                    instrument=request.instrument,
                    start=payload.bar_start,
                    end=payload.bar_end,
                    open=Decimal(str(payload.open)),
                    high=Decimal(str(payload.high)),
                    low=Decimal(str(payload.low)),
                    close=Decimal(str(payload.close)),
                    volume=Decimal(payload.volume),
                    chronology=DataChronology(
                        observed_at=observation.document.observed_at,
                        available_at=observation.document.available_at,
                        as_of_time=request.as_of_time,
                    ),
                )
            )
        status: CoverageStatus = "missing" if not bars else "partial" if missing else "complete"
        return HistoricalBarsResult(
            items=tuple(bars),
            coverage=CoverageReport(
                capability="historical_bars",
                status=status,
                requested_count=len(bars) + len(missing),
                returned_count=len(bars),
                missing_identifiers=tuple(missing),
                detail="legacy Alpha Vantage daily data is not certified point-in-time",
            ),
            provenance=self._provenance(),
            as_of_time=request.as_of_time,
        )

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        report, source = self._unsupported("instrument_discovery")
        return DiscoveryResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def map_identifier(self, request: IdentifierMappingRequest) -> MappingResult:
        report, source = self._unsupported("identifier_mapping")
        return MappingResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def fundamentals(self, request: InstrumentQuery) -> FundamentalsResult:
        report, source = self._unsupported("fundamentals")
        return FundamentalsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def corporate_actions(self, request: HistoricalBarsRequest) -> CorporateActionsResult:
        report, source = self._unsupported("corporate_actions")
        return CorporateActionsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def exchange_calendar(self, request: ExchangeCalendarRequest) -> ExchangeCalendarResult:
        report, source = self._unsupported("exchange_calendars")
        return ExchangeCalendarResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def fx_rates(self, request: FxRatesRequest) -> FxRatesResult:
        report, source = self._unsupported("fx_rates")
        return FxRatesResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def evidence_documents(self, request: EvidenceDocumentRequest) -> EvidenceDocumentsResult:
        report, source = self._unsupported("evidence_documents")
        return EvidenceDocumentsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def _unsupported(self, capability: CapabilityName) -> tuple[CoverageReport, ProviderProvenance]:
        return unsupported(capability, "alpha_vantage_compat", requested_count=1)

    @staticmethod
    def _provenance() -> ProviderProvenance:
        return ProviderProvenance(
            provider_id="alpha_vantage_compat",
            request_id="legacy-observation-collection",
            retrieved_at=datetime.now(UTC),
            license_note="See Alpha Vantage plan terms; historical availability is not certified.",
        )
