"""Versioned, immutable records shared by every evidence source.

An observation is a fact *as supplied by one source at one point in time*.
It is deliberately separate from a graph edge or a model conclusion: later
agents may interpret the same observation differently without changing it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenModel(BaseModel):
    """Reject unknown data and prevent accidental mutation after capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)


SourceKind: TypeAlias = Literal[
    "sec_filing",
    "investor_relations",
    "earnings_call",
    "web_discovery",
    "market_data",
]
SourceTier: TypeAlias = Literal["primary", "official", "discovery", "market_data"]


class SourceDocument(_FrozenModel):
    """An immutable retrieved document or data response with its provenance."""

    document_id: UUID = Field(default_factory=uuid4)
    source_kind: SourceKind
    source_tier: SourceTier
    source_adapter: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuer_entity_id: str = Field(min_length=1)
    observed_at: datetime
    available_at: datetime
    retrieved_at: datetime
    usage_note: str = Field(min_length=1)
    external_id: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _validate_timing(self) -> SourceDocument:
        timestamps = (self.observed_at, self.available_at, self.retrieved_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("source document timestamps must include a timezone")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot precede observed_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("retrieved_at cannot precede available_at")
        return self


class TextEvidence(_FrozenModel):
    payload_type: Literal["text"] = "text"
    text: str = Field(min_length=1)
    exact_quote: str = Field(min_length=1)
    character_start: int = Field(ge=0)
    character_end: int = Field(gt=0)
    section: str | None = None

    @model_validator(mode="after")
    def _validate_span(self) -> TextEvidence:
        if self.character_end <= self.character_start:
            raise ValueError("character_end must be greater than character_start")
        if self.exact_quote not in self.text:
            raise ValueError("exact_quote must be present in text")
        return self


class StructuredFilingFact(_FrozenModel):
    payload_type: Literal["structured_filing_fact"] = "structured_filing_fact"
    fact_name: str = Field(min_length=1)
    fact_value: str = Field(min_length=1)
    unit: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    taxonomy: str | None = None

    @model_validator(mode="after")
    def _validate_period(self) -> StructuredFilingFact:
        if self.period_start is not None and self.period_end is not None:
            if self.period_end < self.period_start:
                raise ValueError("period_end cannot precede period_start")
        return self


class MarketBar(_FrozenModel):
    payload_type: Literal["market_bar"] = "market_bar"
    symbol: str = Field(min_length=1)
    interval: Literal["1d"] = "1d"
    bar_start: datetime
    bar_end: datetime
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_bar(self) -> MarketBar:
        if self.bar_start.tzinfo is None or self.bar_end.tzinfo is None:
            raise ValueError("market-bar timestamps must include a timezone")
        if self.bar_end <= self.bar_start:
            raise ValueError("bar_end must be after bar_start")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be at most open, close, and high")
        return self


class EventSignal(_FrozenModel):
    payload_type: Literal["event_signal"] = "event_signal"
    event_kind: str = Field(min_length=1)
    direction: Literal["positive", "negative", "neutral", "unknown"]
    intensity: float = Field(ge=-1, le=1)
    summary: str = Field(min_length=1)


EvidencePayload: TypeAlias = Annotated[
    TextEvidence | StructuredFilingFact | MarketBar | EventSignal,
    Field(discriminator="payload_type"),
]


class ExtractionProvenance(_FrozenModel):
    """How a source adapter or model produced the observation payload."""

    extractor_name: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    model_provider: str | None = None
    model_name: str | None = None

    @model_validator(mode="after")
    def _validate_model_pair(self) -> ExtractionProvenance:
        if (self.model_provider is None) != (self.model_name is None):
            raise ValueError("model_provider and model_name must be supplied together")
        return self


class EvidenceObservation(_FrozenModel):
    """The common append-only record emitted by every evidence adapter."""

    schema_version: Literal["1"] = "1"
    observation_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(min_length=1)
    document: SourceDocument
    mentioned_entity_ids: tuple[str, ...] = Field(min_length=1)
    payload: EvidencePayload
    extraction: ExtractionProvenance

    @model_validator(mode="after")
    def _validate_entities(self) -> EvidenceObservation:
        if len(set(self.mentioned_entity_ids)) != len(self.mentioned_entity_ids):
            raise ValueError("mentioned_entity_ids must not contain duplicates")
        if self.document.issuer_entity_id not in self.mentioned_entity_ids:
            raise ValueError("mentioned_entity_ids must include the issuer_entity_id")
        return self


class SourceCatalogEntry(_FrozenModel):
    """Versioned configuration for an allowed source; entries are never edited in place."""

    schema_version: Literal["1"] = "1"
    entry_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(min_length=1)
    issuer_entity_id: str = Field(min_length=1)
    source_kind: SourceKind
    source_tier: SourceTier
    source_adapter: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    polling_hint: Literal["event_driven", "nightly", "quarterly", "manual"] = "nightly"
    usage_note: str = Field(min_length=1)
    registered_at: datetime

    @model_validator(mode="after")
    def _validate_registered_at(self) -> SourceCatalogEntry:
        if self.registered_at.tzinfo is None:
            raise ValueError("registered_at must include a timezone")
        return self


class EvidenceRunReceipt(_FrozenModel):
    """Append-only receipt for one adapter collection run."""

    schema_version: Literal["1"] = "1"
    receipt_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    adapter_name: str = Field(min_length=1)
    status: Literal["completed", "partial", "failed"]
    started_at: datetime
    finished_at: datetime
    observation_idempotency_keys: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_timing(self) -> EvidenceRunReceipt:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("run-receipt timestamps must include a timezone")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if self.status == "completed" and self.errors:
            raise ValueError("a completed receipt cannot contain errors")
        return self
