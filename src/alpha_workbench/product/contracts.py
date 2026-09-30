"""Versioned contracts shared by the production application components."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import canonical_json, content_sha256

SelectionMode = Literal["current", "point_in_time"]
Cadence = Literal["daily", "weekly", "monthly"]


def _now_utc() -> datetime:
    return datetime.now(UTC)


class ContractBase(BaseModel):
    """Base for immutable, canonicalizable product records.

    Versioned records are append-only in persistence.  ``frozen`` catches
    accidental top-level mutation in application code; repositories enforce
    the stronger no-overwrite rule for stored rows.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    schema_version: str = "1"
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    def canonical_json(self) -> str:
        return canonical_json(self)

    def content_sha256(self) -> str:
        return content_sha256(self)

    @property
    def version_key(self) -> str:
        identifier = getattr(self, "workspace_id", None) or getattr(self, "universe_id", None)
        identifier = identifier or getattr(self, "strategy_id", None) or getattr(
            self, "run_id", None
        )
        identifier = identifier or getattr(self, "package_id", None)
        if identifier is None:
            raise AttributeError("contract does not expose a versioned identifier")
        return f"{identifier}:v{self.version}"


class InstrumentRef(ContractBase):
    """A tradeable instrument, distinct from its economic entity."""

    instrument_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    country: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    asset_class: Literal["equity", "etf", "adr", "future", "option", "cash"] = "equity"
    entity_id: str | None = None
    figi: str | None = None
    provider_symbols: dict[str, str] = Field(default_factory=dict)


class UniverseSpec(ContractBase):
    """Point-in-time or current basket used by a workspace or strategy."""

    universe_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    instruments: tuple[InstrumentRef, ...] = Field(min_length=1)
    selection_time: datetime
    selection_mode: SelectionMode
    selection_method: str = Field(min_length=1)
    target_count: int = Field(default=10, ge=1)
    benchmark: str | None = None
    base_currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("selection_time")
    @classmethod
    def require_selection_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selection_time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def unique_instruments(self) -> UniverseSpec:
        ids = [instrument.instrument_id for instrument in self.instruments]
        if len(ids) != len(set(ids)):
            raise ValueError("universe contains duplicate instrument IDs")
        if self.target_count < len(self.instruments):
            raise ValueError("target_count cannot be smaller than the selected instrument count")
        return self

    @property
    def as_of_time(self) -> datetime:
        """Compatibility alias used by historical panels."""

        return self.selection_time


class DomainWorkspace(ContractBase):
    """A durable domain-to-strategy workspace."""

    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    cadence: Cadence = "daily"
    regions: tuple[str, ...] = ()
    universe_id: str | None = None
    graph_version_id: str | None = None
    status: Literal["draft", "building", "ready", "degraded", "archived"] = "draft"
    provider_ids: tuple[str, ...] = ()


class ProviderCapability(ContractBase):
    """Declared data capability and point-in-time guarantees of a provider."""

    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    markets: tuple[str, ...] = ()
    frequencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    supports_point_in_time: bool = False
    supports_corporate_actions: bool = False
    supports_global_equities: bool = False
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    licensing_note: str = ""


class StrategySpec(ContractBase):
    """Engine-neutral executable strategy definition."""

    strategy_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    universe_id: str = Field(min_length=1)
    cadence: Cadence = "daily"
    prediction_horizon: str = Field(default="1d", min_length=1)
    signal_expression: str = Field(min_length=1, max_length=10_000)
    feature_names: tuple[str, ...] = Field(min_length=1)
    portfolio_config: dict[str, Any] = Field(default_factory=dict)
    risk_config: dict[str, Any] = Field(default_factory=dict)
    execution_config: dict[str, Any] = Field(default_factory=dict)
    validation_config: dict[str, Any] = Field(default_factory=dict)
    dataset_version_ids: tuple[str, ...] = ()
    graph_version_id: str | None = None
    status: Literal["draft", "testing", "validated", "experimental", "retired"] = "draft"


class StrategyRun(ContractBase):
    """Immutable record of one strategy evaluation."""

    run_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    dataset_version_ids: tuple[str, ...] = ()
    graph_version_id: str | None = None
    train_window: tuple[datetime, datetime] | None = None
    validation_window: tuple[datetime, datetime] | None = None
    test_window: tuple[datetime, datetime] | None = None
    trial_count: int = Field(default=1, ge=1)
    metrics: dict[str, float | int | None] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()


class StrategyPackage(ContractBase):
    """Reproducible executable/export artifact for a strategy run."""

    package_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    format: Literal["lean", "zip", "json"] = "lean"
    artifact_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    manifest: dict[str, Any] = Field(default_factory=dict)
    storage_uri: str = Field(min_length=1)


class ReadinessCheck(ContractBase):
    """One deterministic readiness check for a workspace or strategy."""

    name: str = Field(min_length=1)
    status: Literal["pass", "warn", "fail"]
    detail: str = ""
    checked_at: datetime = Field(default_factory=_now_utc)

    @field_validator("checked_at")
    @classmethod
    def checked_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value


class ReadinessReport(ContractBase):
    """Aggregate deterministic readiness result used by the application shell."""

    readiness_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    status: Literal["ready", "degraded", "not_ready"]
    checks: tuple[ReadinessCheck, ...] = Field(min_length=1)
    evaluated_at: datetime = Field(default_factory=_now_utc)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def status_matches_checks(self) -> ReadinessReport:
        has_fail = any(check.status == "fail" for check in self.checks)
        has_warn = any(check.status == "warn" for check in self.checks)
        expected = "not_ready" if has_fail else "degraded" if has_warn else "ready"
        if self.status != expected:
            raise ValueError(f"readiness status must be {expected!r} for the supplied checks")
        return self

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"
