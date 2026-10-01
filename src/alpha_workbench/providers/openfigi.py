"""OpenFIGI identifier mapping adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from .base import LocalRequestBudget, credential_from_env, post_json, provenance, unsupported
from .contracts import (
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
    HistoricalBarsRequest,
    HistoricalBarsResult,
    IdentifierMapping,
    IdentifierMappingRequest,
    InstrumentQuery,
    MappingResult,
    ProviderBudget,
    ProviderCapability,
)

_URL = "https://api.openfigi.com/v3/mapping"


class OpenFigiAdapter:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        max_requests_per_minute: int = 25,
        max_requests_per_run: int = 1000,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=20.0)
        self._budget = ProviderBudget(
            max_requests_per_minute=max_requests_per_minute,
            max_requests_per_run=max_requests_per_run,
        )
        self._limiter = LocalRequestBudget(self._budget)
        self._capability = ProviderCapability(
            provider_id="openfigi",
            display_name="OpenFIGI",
            capabilities=("identifier_mapping",),
            supports_point_in_time=False,
            rate_limit_per_minute=max_requests_per_minute,
            licensing_note="OpenFIGI mapping metadata; review terms before redistribution.",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> OpenFigiAdapter:
        budget = config.get("budget", {})
        if not isinstance(budget, dict):
            raise ValueError("OpenFIGI budget must be a mapping")
        return cls(
            api_key=credential_from_env(config, "OPENFIGI_API_KEY"),
            max_requests_per_minute=int(budget.get("max_requests_per_minute", 25)),
            max_requests_per_run=int(budget.get("max_requests_per_run", 1000)),
        )

    @property
    def capability(self) -> ProviderCapability:
        return self._capability

    @property
    def budget(self) -> ProviderBudget:
        return self._budget

    def map_identifier(self, request: IdentifierMappingRequest) -> MappingResult:
        if request.identifier_type == "symbol" and not request.exchange:
            coverage = CoverageReport(
                capability="identifier_mapping",
                status="missing",
                requested_count=1,
                missing_identifiers=(request.identifier_value,),
                detail="symbol mapping requires an exchange to disambiguate listings",
            )
            return MappingResult(
                items=(),
                coverage=coverage,
                provenance=provenance("openfigi"),
                as_of_time=request.as_of_time,
            )
        id_type = {
            "symbol": "TICKER",
            "figi": "ID_BB_GLOBAL",
            "composite_figi": "ID_BB_GLOBAL_SHARE_CLASS",
            "isin": "ID_ISIN",
            "cusip": "ID_CUSIP",
            "sedol": "ID_SEDOL",
            "lei": "ID_LEI",
        }[request.identifier_type]
        job: dict[str, str] = {"idType": id_type, "idValue": request.identifier_value}
        if request.exchange:
            job["micCode"] = request.exchange
        headers = {"X-OPENFIGI-APIKEY": self._api_key} if self._api_key else None
        payload = post_json(self._client, _URL, [job], budget=self._limiter, headers=headers)
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise ValueError("OpenFIGI response had an invalid mapping shape")
        retrieved_at = datetime.now(UTC)
        result = payload[0]
        raw_data = result.get("data", [])
        if not isinstance(raw_data, list):
            raw_data = []
        candidates = [row for row in raw_data if isinstance(row, dict)]
        if request.exchange:
            candidates = [
                row
                for row in candidates
                if row.get("exchCode") == request.exchange or row.get("micCode") == request.exchange
            ]
        if retrieved_at > request.as_of_time:
            return MappingResult(
                items=(),
                coverage=CoverageReport(
                    capability="identifier_mapping",
                    status="missing",
                    requested_count=1,
                    missing_identifiers=(request.identifier_value,),
                    detail="mapping was retrieved after as_of_time",
                ),
                provenance=provenance("openfigi", source_url=_URL),
                as_of_time=request.as_of_time,
            )
        # Multiple listings are never silently collapsed to an arbitrary security.
        if len(candidates) > 1:
            return MappingResult(
                items=(),
                coverage=CoverageReport(
                    capability="identifier_mapping",
                    status="partial",
                    requested_count=1,
                    returned_count=0,
                    missing_identifiers=(request.identifier_value,),
                    detail="ambiguous mapping; provide an exchange or FIGI",
                ),
                provenance=provenance("openfigi", source_url=_URL),
                as_of_time=request.as_of_time,
            )
        mappings = tuple(self._mapping(row, request, retrieved_at) for row in candidates)
        status: CoverageStatus = "complete" if mappings else "missing"
        coverage = CoverageReport(
            capability="identifier_mapping",
            status=status,
            requested_count=1,
            returned_count=len(mappings),
            missing_identifiers=() if mappings else (request.identifier_value,),
            detail="" if mappings else str(result.get("warning", "no mapping found")),
        )
        return MappingResult(
            items=mappings,
            coverage=coverage,
            provenance=provenance("openfigi", source_url=_URL),
            as_of_time=request.as_of_time,
        )

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        report, source = unsupported(
            "instrument_discovery",
            "openfigi",
            requested_count=1,
            detail=(
                "OpenFIGI maps supplied identifiers; it does not provide natural-language discovery"
            ),
        )
        return DiscoveryResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def fundamentals(self, request: InstrumentQuery) -> FundamentalsResult:
        report, source = unsupported("fundamentals", "openfigi", requested_count=1)
        return FundamentalsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult:
        report, source = unsupported("historical_bars", "openfigi", requested_count=1)
        return HistoricalBarsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def corporate_actions(self, request: HistoricalBarsRequest) -> CorporateActionsResult:
        report, source = unsupported("corporate_actions", "openfigi", requested_count=1)
        return CorporateActionsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def exchange_calendar(self, request: ExchangeCalendarRequest) -> ExchangeCalendarResult:
        report, source = unsupported("exchange_calendars", "openfigi", requested_count=1)
        return ExchangeCalendarResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def fx_rates(self, request: FxRatesRequest) -> FxRatesResult:
        report, source = unsupported("fx_rates", "openfigi", requested_count=1)
        return FxRatesResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def evidence_documents(self, request: EvidenceDocumentRequest) -> EvidenceDocumentsResult:
        report, source = unsupported("evidence_documents", "openfigi", requested_count=1)
        return EvidenceDocumentsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    @staticmethod
    def _mapping(
        row: dict[str, Any], request: IdentifierMappingRequest, retrieved_at: datetime
    ) -> IdentifierMapping:
        return IdentifierMapping(
            figi=str(row["figi"]),
            composite_figi=row.get("compositeFIGI"),
            share_class_figi=row.get("shareClassFIGI"),
            ticker=row.get("ticker"),
            name=row.get("name"),
            exchange_code=row.get("exchCode"),
            security_type=row.get("securityType"),
            security_type2=row.get("securityType2"),
            chronology=DataChronology(
                observed_at=retrieved_at,
                available_at=retrieved_at,
                as_of_time=request.as_of_time,
            ),
            original_request=request,
        )
