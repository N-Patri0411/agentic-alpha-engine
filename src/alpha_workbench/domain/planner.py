"""Deterministic domain expansion and explainable universe selection."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from math import log10
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alpha_workbench.product import InstrumentRef, UniverseSpec
from alpha_workbench.product.contracts import SelectionMode


class DomainSpec(BaseModel):
    """Typed interpretation of a user's domain and selection constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    description: str = Field(min_length=2)
    normalized_domain: str = Field(min_length=2)
    expanded_concepts: tuple[str, ...] = Field(min_length=1)
    regions: tuple[str, ...] = ("global",)
    cadence: Literal["daily", "weekly", "monthly"] = "daily"
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    selection_mode: SelectionMode = "current"
    selection_time: datetime
    target_count: int = Field(default=10, ge=1, le=100)

    @field_validator("selection_time")
    @classmethod
    def aware_selection_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selection_time must be timezone-aware")
        return value


class DomainCandidate(BaseModel):
    """Provider-resolved listing and data quality facts used by the planner."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    instrument_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    exchange: str = Field(min_length=1)
    country: str = Field(min_length=2)
    currency: str = Field(min_length=3, max_length=3)
    figi: str | None = None
    provider_symbols: dict[str, str] = Field(default_factory=dict)
    asset_class: Literal["equity", "adr", "etf"] = "equity"
    company_name: str = Field(min_length=1)
    concepts: tuple[str, ...] = ()
    sub_industry: str = Field(min_length=1)
    region: str = Field(min_length=1)
    relevance: float = Field(ge=0, le=1)
    average_daily_value_usd: float = Field(ge=0)
    data_coverage: float = Field(ge=0, le=1)
    available: bool = True
    canonical_id_resolved: bool = True
    point_in_time_verified: bool = False
    active_from: datetime | None = None
    active_to: datetime | None = None
    ambiguity_group: str | None = None
    resolution_rank: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def valid_active_range(self) -> DomainCandidate:
        if self.active_from and self.active_to and self.active_to < self.active_from:
            raise ValueError("active_to cannot precede active_from")
        return self


class InstrumentDecision(BaseModel):
    """A selected or rejected candidate with the evidence for that decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: DomainCandidate
    relevance_score: float
    liquidity_score: float
    coverage_score: float
    total_score: float
    reason: str
    locked: bool = False

    def instrument_ref(self) -> InstrumentRef:
        return InstrumentRef(
            instrument_id=self.candidate.instrument_id,
            symbol=self.candidate.symbol,
            exchange=self.candidate.exchange,
            country=self.candidate.country,
            currency=self.candidate.currency,
            asset_class=self.candidate.asset_class,
            figi=self.candidate.figi,
            provider_symbols=self.candidate.provider_symbols,
        )


class DomainPlan(BaseModel):
    """Reviewable output of domain discovery and universe construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["ready", "insufficient_candidates", "locked"] = "ready"
    domain_spec: DomainSpec
    selection_method: str = Field(min_length=1)
    methodology: tuple[str, ...] = ()
    provider_coverage: dict[str, float] = Field(default_factory=dict)
    discovery_yield: dict[str, float] = Field(default_factory=dict)
    recommended: tuple[InstrumentDecision, ...] = ()
    rejected: tuple[InstrumentDecision, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def selected_unique(self) -> DomainPlan:
        ids = [item.candidate.instrument_id for item in self.recommended]
        if len(ids) != len(set(ids)):
            raise ValueError("recommended instruments must be unique")
        if len(self.recommended) > self.domain_spec.target_count:
            raise ValueError("recommendations exceed target_count")
        return self

    def to_universe_spec(
        self, workspace_id: str, *, universe_id: str | None = None
    ) -> UniverseSpec:
        if not self.recommended:
            raise ValueError("cannot lock a plan without selected instruments")
        if len(self.recommended) != self.domain_spec.target_count:
            raise ValueError("cannot lock until target_count instruments are selected")
        return UniverseSpec(
            universe_id=universe_id or str(uuid4()),
            workspace_id=workspace_id,
            domain=self.domain_spec.normalized_domain,
            instruments=tuple(item.instrument_ref() for item in self.recommended),
            selection_time=self.domain_spec.selection_time,
            selection_mode=self.domain_spec.selection_mode,
            selection_method=self.selection_method,
            target_count=self.domain_spec.target_count,
            base_currency=self.domain_spec.base_currency,
        )


_CONCEPTS: dict[str, tuple[str, ...]] = {
    "semiconductor": (
        "semiconductors",
        "integrated circuits",
        "chip manufacturing",
        "foundries",
        "wafer fabrication",
        "semiconductor equipment",
        "lithography",
        "deposition",
        "etch",
        "advanced packaging",
        "chip testing",
        "memory chips",
        "silicon wafers",
    ),
    "semiconductor manufacturing": (
        "semiconductors",
        "integrated circuits",
        "chip manufacturing",
        "foundries",
        "wafer fabrication",
        "semiconductor equipment",
        "lithography",
        "deposition",
        "etch",
        "advanced packaging",
        "chip testing",
        "memory chips",
        "silicon wafers",
    ),
    "artificial intelligence": ("artificial intelligence", "machine learning", "AI compute"),
    "renewable energy": ("renewable energy", "solar power", "wind power", "grid storage"),
}


def parse_domain_spec(
    description: str,
    *,
    regions: tuple[str, ...] = ("global",),
    cadence: Literal["daily", "weekly", "monthly"] = "daily",
    base_currency: str = "USD",
    selection_mode: SelectionMode = "current",
    selection_time: datetime,
    target_count: int = 10,
) -> DomainSpec:
    """Expand common business descriptions using a deterministic concept catalog."""

    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", description.casefold()).split())
    concepts = _CONCEPTS.get(normalized)
    if concepts is None:
        concepts = (normalized,)
    return DomainSpec(
        description=description,
        normalized_domain=normalized,
        expanded_concepts=concepts,
        regions=regions or ("global",),
        cadence=cadence,
        base_currency=base_currency.upper(),
        selection_mode=selection_mode,
        selection_time=selection_time,
        target_count=target_count,
    )


def _region_matches(
    candidate_region: str, candidate_country: str, requested_regions: tuple[str, ...]
) -> bool:
    normalized = {region.casefold() for region in requested_regions}
    return (
        "global" in normalized
        or candidate_region.casefold() in normalized
        or candidate_country.casefold() in normalized
    )


class DomainPlanner:
    """Build deterministic, diversified recommendations from resolved candidates."""

    minimum_relevance = 0.35
    minimum_coverage = 0.25

    def plan(
        self,
        spec: DomainSpec,
        candidates: tuple[DomainCandidate, ...],
        *,
        plan_id: str | None = None,
        provider_coverage: dict[str, float] | None = None,
        discovery_yield: dict[str, float] | None = None,
    ) -> DomainPlan:
        decisions = [self._score(item) for item in self._canonicalize(candidates)]
        rejected: list[InstrumentDecision] = []
        eligible: list[InstrumentDecision] = []
        cutoff = spec.selection_time.astimezone(UTC)
        for decision in decisions:
            candidate = decision.candidate
            reason: str | None = None
            if not candidate.available:
                reason = "Rejected because the instrument is unavailable from configured providers."
            elif not candidate.canonical_id_resolved:
                reason = (
                    "Rejected because no canonical FIGI could be resolved for this "
                    "exchange listing."
                )
            elif candidate.relevance < self.minimum_relevance:
                reason = "Rejected because domain relevance is below the 0.35 threshold."
            elif candidate.data_coverage < self.minimum_coverage:
                reason = "Rejected because data coverage is below the 0.25 threshold."
            elif not _region_matches(candidate.region, candidate.country, spec.regions):
                reason = "Rejected because its region is outside the requested regions."
            elif spec.selection_mode == "point_in_time" and (
                not candidate.point_in_time_verified
                and (candidate.active_from is None or candidate.active_from > cutoff)
            ):
                reason = "Rejected because listing activity is not established by selection_time."
            elif candidate.active_from and candidate.active_from > cutoff:
                reason = "Rejected because the instrument was not yet active at selection_time."
            elif candidate.active_to and candidate.active_to < cutoff:
                reason = "Rejected because the instrument was inactive at selection_time."
            if reason:
                rejected.append(decision.model_copy(update={"reason": reason}))
            else:
                eligible.append(decision)

        selected = self._diversify(eligible, spec.target_count)
        selected_ids = {item.candidate.instrument_id for item in selected}
        rejected.extend(
            item.model_copy(
                update={
                    "reason": (
                        "Not selected: a higher-scoring listing was chosen while preserving "
                        "sub-industry and regional breadth."
                    )
                }
            )
            for item in eligible
            if item.candidate.instrument_id not in selected_ids
        )
        warnings: list[str] = []
        if len(selected) < spec.target_count:
            warnings.append(
                f"Only {len(selected)} eligible instruments were found for "
                f"target_count {spec.target_count}."
            )
        return DomainPlan(
            plan_id=plan_id or str(uuid4()),
            status="ready" if len(selected) == spec.target_count else "insufficient_candidates",
            domain_spec=spec,
            selection_method="domain-relevance-liquidity-coverage-diversification-v1",
            methodology=(
                "Relevance uses provider/domain match on a 0 to 1 scale; candidates below "
                "0.35 are rejected.",
                "Liquidity score is log-scaled average daily traded value in USD, capped at $1B.",
                "Coverage score is the provider's fraction of required historical fields "
                "available.",
                "Total score weights relevance 50%, liquidity 25%, and data coverage 25%.",
                "Selection applies a bounded diversity bonus of 0.10 per repeated "
                "sub-industry and 0.04 per repeated region; raw score breaks adjusted-score "
                "ties.",
                "Point-in-time candidates require an explicit provider guarantee or a "
                "listing active date no later than selection_time.",
                "Ambiguous listings are resolved by provider resolution rank, then FIGI "
                "presence, then canonical ID.",
            ),
            provider_coverage=provider_coverage or {},
            discovery_yield=discovery_yield or {},
            recommended=tuple(selected),
            rejected=tuple(
                sorted(rejected, key=lambda item: (-item.total_score, item.candidate.instrument_id))
            ),
            warnings=tuple(warnings),
        )

    def _canonicalize(self, candidates: tuple[DomainCandidate, ...]) -> tuple[DomainCandidate, ...]:
        by_id: dict[str, DomainCandidate] = {}
        for item in candidates:
            current = by_id.get(item.instrument_id)
            if current is None or self._resolution_key(item) < self._resolution_key(current):
                by_id[item.instrument_id] = item
        groups: dict[str, list[DomainCandidate]] = {}
        for item in by_id.values():
            if item.ambiguity_group:
                groups.setdefault(item.ambiguity_group, []).append(item)
        ambiguous_losers = {
            item.instrument_id
            for group in groups.values()
            if len(group) > 1
            for item in sorted(group, key=self._resolution_key)[1:]
        }
        # Keep lower-ranked alternatives visible to the rejection list by assigning a
        # zero relevance score. Their canonical ID and exchange remain inspectable.
        return tuple(
            item.model_copy(update={"relevance": 0.0})
            if item.instrument_id in ambiguous_losers
            else item
            for item in sorted(by_id.values(), key=lambda value: value.instrument_id)
        )

    @staticmethod
    def _resolution_key(candidate: DomainCandidate) -> tuple[int, int, str, str]:
        return (
            candidate.resolution_rank,
            0 if candidate.figi else 1,
            candidate.exchange,
            candidate.instrument_id,
        )

    @staticmethod
    def _score(candidate: DomainCandidate) -> InstrumentDecision:
        liquidity = min(1.0, max(0.0, log10(candidate.average_daily_value_usd + 1) / 9))
        coverage = candidate.data_coverage
        relevance = candidate.relevance
        total = 0.50 * relevance + 0.25 * liquidity + 0.25 * coverage
        reason = (
            f"{candidate.company_name} matches the domain at {relevance:.2f}; "
            f"liquidity is {liquidity:.2f} and data coverage is {coverage:.2f}. "
            f"Canonical listing {candidate.symbol} on {candidate.exchange}"
            + (f" (FIGI {candidate.figi})" if candidate.figi else " (FIGI unavailable)")
            + f" scores {total:.3f}."
        )
        return InstrumentDecision(
            candidate=candidate,
            relevance_score=relevance,
            liquidity_score=liquidity,
            coverage_score=coverage,
            total_score=total,
            reason=reason,
        )

    @staticmethod
    def _diversify(
        eligible: list[InstrumentDecision], target_count: int
    ) -> list[InstrumentDecision]:
        pool = sorted(
            eligible,
            key=lambda item: (-item.total_score, item.candidate.instrument_id),
        )
        selected: list[InstrumentDecision] = []
        industry_counts: dict[str, int] = {}
        region_counts: dict[str, int] = {}
        while pool and len(selected) < target_count:

            def priority(item: InstrumentDecision) -> tuple[float, float, str]:
                diversity_bonus = 0.10 * industry_counts.get(
                    item.candidate.sub_industry, 0
                ) + 0.04 * region_counts.get(item.candidate.region, 0)
                return (
                    -(item.total_score - diversity_bonus),
                    -item.total_score,
                    item.candidate.instrument_id,
                )

            choice = min(pool, key=priority)
            pool.remove(choice)
            selected.append(choice)
            industry = choice.candidate.sub_industry
            region = choice.candidate.region
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            region_counts[region] = region_counts.get(region, 0) + 1
        return selected
