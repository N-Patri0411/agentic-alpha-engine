"""Typed, provider-neutral contracts for external financial data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CapabilityName = Literal[
    "instrument_discovery",
    "identifier_mapping",
    "historical_bars",
    "fundamentals",
    "corporate_actions",
    "exchange_calendars",
    "fx_rates",
    "evidence_documents",
]
CoverageStatus = Literal["complete", "partial", "missing", "unsupported", "error"]
IdentifierType = Literal["symbol", "figi", "composite_figi", "isin", "cusip", "sedol", "lei"]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @model_validator(mode="after")
    def datetime_fields_are_aware(self) -> ProviderModel:
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        return self


class ProviderCapability(ProviderModel):
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    capabilities: tuple[CapabilityName, ...] = ()
    markets: tuple[str, ...] = ()
    frequencies: tuple[str, ...] = ()
    supports_point_in_time: bool = False
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    estimated_cost_per_request: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    licensing_note: str = ""


class ProviderCatalogEntry(ProviderModel):
    """Catalog metadata is safe to expose even when credentials are absent."""

    capability: ProviderCapability
    configured: bool
    credentials_env: str | None = None
    limitation: str = ""


class ProviderBudget(ProviderModel):
    """Local-call guardrails; cost is an estimate, never a vendor invoice."""

    max_requests_per_minute: int | None = Field(default=None, ge=1)
    max_requests_per_run: int | None = Field(default=None, ge=1)
    max_estimated_cost: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ProviderProvenance(ProviderModel):
    provider_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    retrieved_at: datetime
    source_url: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    license_note: str = ""

    @field_validator("source_url")
    @classmethod
    def require_http_url(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("source_url must be an absolute HTTP or HTTPS URL")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value


class DataChronology(ProviderModel):
    observed_at: datetime
    available_at: datetime
    as_of_time: datetime

    @model_validator(mode="after")
    def availability_follows_observation(self) -> DataChronology:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self

    @field_validator("observed_at", "available_at", "as_of_time")
    @classmethod
    def chronology_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("chronology timestamps must be timezone-aware")
        return value


class CoverageReport(ProviderModel):
    capability: CapabilityName
    status: CoverageStatus
    requested_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    missing_identifiers: tuple[str, ...] = ()
    detail: str = ""

    @model_validator(mode="after")
    def counts_are_consistent(self) -> CoverageReport:
        if self.returned_count > self.requested_count:
            raise ValueError("returned_count cannot exceed requested_count")
        if self.status == "complete" and self.returned_count < self.requested_count:
            raise ValueError("complete coverage must account for every requested item")
        if self.status == "missing" and self.returned_count:
            raise ValueError("missing coverage cannot contain returned items")
        return self


class InstrumentQuery(ProviderModel):
    query: str = Field(min_length=1)
    exchange: str | None = None
    country: str | None = None
    as_of_time: datetime


class InstrumentRecord(ProviderModel):
    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    name: str = ""
    figi: str | None = None
    isin: str | None = None
    currency: str | None = None
    country: str | None = None
    asset_class: str | None = None
    provider_symbol: str | None = None


class IdentifierMappingRequest(ProviderModel):
    identifier_type: IdentifierType
    identifier_value: str = Field(min_length=1)
    exchange: str | None = None
    as_of_time: datetime


class IdentifierMapping(ProviderModel):
    figi: str = Field(min_length=1)
    composite_figi: str | None = None
    share_class_figi: str | None = None
    ticker: str | None = None
    name: str | None = None
    exchange_code: str | None = None
    security_type: str | None = None
    security_type2: str | None = None
    chronology: DataChronology
    original_request: IdentifierMappingRequest


class HistoricalBarsRequest(ProviderModel):
    instrument: InstrumentRecord
    start: date
    end: date
    interval: Literal["daily", "weekly", "monthly"] = "daily"
    as_of_time: datetime

    @model_validator(mode="after")
    def valid_range(self) -> HistoricalBarsRequest:
        if self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class HistoricalBar(ProviderModel):
    instrument: InstrumentRecord
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adjusted_close: Decimal | None = None
    chronology: DataChronology

    @model_validator(mode="after")
    def valid_bar(self) -> HistoricalBar:
        if self.end <= self.start:
            raise ValueError("bar end must follow bar start")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is inconsistent")
        if self.low > min(self.open, self.close):
            raise ValueError("bar low is inconsistent")
        return self


class FundamentalRecord(ProviderModel):
    instrument: InstrumentRecord
    metric: str = Field(min_length=1)
    value: str | int | float | Decimal | None
    period_end: date | None = None
    filed_at: datetime | None = None
    chronology: DataChronology


class CorporateAction(ProviderModel):
    instrument: InstrumentRecord
    action_type: Literal["dividend", "split", "other"]
    ex_date: date
    record_date: date | None = None
    payment_date: date | None = None
    amount: Decimal | None = None
    ratio: Decimal | None = None
    currency: str | None = None
    chronology: DataChronology


class ExchangeCalendarRequest(ProviderModel):
    exchange: str = Field(min_length=1)
    start: date
    end: date
    as_of_time: datetime

    @model_validator(mode="after")
    def valid_range(self) -> ExchangeCalendarRequest:
        if self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class CalendarSession(ProviderModel):
    exchange: str = Field(min_length=1)
    session_date: date
    open_at: datetime
    close_at: datetime
    is_holiday: bool = False
    chronology: DataChronology


class FxRatesRequest(ProviderModel):
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    start: date
    end: date
    as_of_time: datetime

    @model_validator(mode="after")
    def valid_range(self) -> FxRatesRequest:
        if self.end < self.start:
            raise ValueError("end must not precede start")
        return self


class FxRate(ProviderModel):
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    observed_at: datetime
    available_at: datetime
    as_of_time: datetime


class EvidenceDocumentRequest(ProviderModel):
    query: str = Field(min_length=1)
    instrument: InstrumentRecord | None = None
    as_of_time: datetime


class EvidenceDocument(ProviderModel):
    title: str = Field(min_length=1)
    url: str
    document_type: str
    published_at: datetime | None = None
    observed_at: datetime
    available_at: datetime
    content_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    license_note: str = ""

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute HTTP or HTTPS URL")
        return value

    @model_validator(mode="after")
    def availability_follows_observation(self) -> EvidenceDocument:
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        return self


ResultItem = TypeVar("ResultItem")


class ProviderResult(ProviderModel, Generic[ResultItem]):
    items: tuple[ResultItem, ...] = ()
    coverage: CoverageReport
    provenance: ProviderProvenance
    as_of_time: datetime

    @model_validator(mode="after")
    def no_items_after_as_of(self) -> ProviderResult[ResultItem]:
        for item in self.items:
            chronology = getattr(item, "chronology", None)
            available_at = getattr(chronology, "available_at", None)
            if available_at is None:
                available_at = getattr(item, "available_at", None)
            if available_at is not None and available_at > self.as_of_time:
                raise ValueError("provider result contains data unavailable at as_of_time")
        return self


DiscoveryResult = ProviderResult[InstrumentRecord]
MappingResult = ProviderResult[IdentifierMapping]
HistoricalBarsResult = ProviderResult[HistoricalBar]
FundamentalsResult = ProviderResult[FundamentalRecord]
CorporateActionsResult = ProviderResult[CorporateAction]
ExchangeCalendarResult = ProviderResult[CalendarSession]
FxRatesResult = ProviderResult[FxRate]
EvidenceDocumentsResult = ProviderResult[EvidenceDocument]
