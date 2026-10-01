"""API routes for provider-aware domain and universe planning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alpha_workbench.domain import (
    DomainCandidate,
    DomainPlan,
    DomainPlanner,
    DomainSpec,
    parse_domain_spec,
)
from alpha_workbench.persistence.repositories import (
    DomainLockRepository,
    ProductRepository,
    RepositoryNotFoundError,
    UniverseRepository,
)
from alpha_workbench.product import DomainWorkspace, UniverseSpec
from alpha_workbench.providers.contracts import (
    FxRatesRequest,
    HistoricalBarsRequest,
    IdentifierMappingRequest,
    InstrumentQuery,
    InstrumentRecord,
)
from alpha_workbench.providers.protocols import ProviderAdapter
from alpha_workbench.providers.registry import ProviderRegistry


class DomainPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=2)
    regions: tuple[str, ...] = ("global",)
    cadence: Literal["daily", "weekly", "monthly"] = "daily"
    base_currency: str = Field(default="USD", min_length=3, max_length=3)
    selection_mode: Literal["current", "point_in_time"] = "current"
    selection_time: datetime | None = None
    target_count: int = Field(default=10, ge=1, le=100)

    @field_validator("selection_time")
    @classmethod
    def selection_time_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("selection_time must include a UTC offset")
        return value


class ProviderCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_ids: tuple[str, ...] = Field(default=(), max_length=32)


class ReplaceInstrumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remove_instrument_id: str = Field(min_length=1)
    replacement_instrument_id: str = Field(min_length=1)


class LockPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_name: str = Field(min_length=1)


class DomainPlanItemResponse(BaseModel):
    instrument_id: str
    symbol: str
    exchange: str
    country: str
    currency: str
    figi: str | None
    provider_symbols: dict[str, str]
    asset_class: str
    company_name: str
    concepts: tuple[str, ...]
    sub_industry: str
    region: str
    relevance_score: int = Field(ge=0, le=100, description="Percentage: 100 means 1.0.")
    liquidity_score: int = Field(ge=0, le=100, description="Percentage: 100 means 1.0.")
    coverage_score: int = Field(ge=0, le=100, description="Percentage: 100 means 1.0.")
    total_score: int = Field(ge=0, le=100, description="Weighted percentage: 100 means 1.0.")
    reason: str
    locked: bool = False


class DomainPlanResponse(BaseModel):
    plan_id: str
    status: str
    domain_spec: dict[str, Any]
    selection_time: datetime
    selection_mode: str
    selection_method: str
    methodology: tuple[str, ...]
    provider_coverage: dict[str, float]
    discovery_yield: dict[str, float]
    recommended: tuple[DomainPlanItemResponse, ...]
    rejected: tuple[DomainPlanItemResponse, ...]
    replacement_candidates: tuple[DomainPlanItemResponse, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _PlanState:
    plan: DomainPlan
    candidates: tuple[DomainCandidate, ...]
    excluded_ids: set[str] = field(default_factory=set)


class DomainApiDependencies:
    """Plan state and injected dependencies for the domain router."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        workspace_repository: ProductRepository,
        universe_repository: UniverseRepository | None = None,
        domain_lock_repository: DomainLockRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.workspace_repository = workspace_repository
        self.universe_repository = universe_repository
        self.domain_lock_repository = domain_lock_repository
        self.clock = clock or (lambda: datetime.now(UTC))
        self.plans: dict[str, _PlanState] = {}


def create_domain_router(dependencies: DomainApiDependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/api/providers/capabilities")
    def provider_capabilities() -> list[dict[str, Any]]:
        return [
            {
                "provider_id": entry.capability.provider_id,
                "display_name": entry.capability.display_name,
                "capabilities": list(entry.capability.capabilities),
                "supports_point_in_time": entry.capability.supports_point_in_time,
                "configured": entry.configured,
                "coverage": "declared" if entry.configured else "unconfigured",
                "limitations": [entry.limitation] if entry.limitation else [],
            }
            for entry in dependencies.provider_registry.list_catalog()
        ]

    @router.post("/api/providers/check")
    def check_providers(request: ProviderCheckRequest) -> list[dict[str, Any]]:
        available = {
            entry.capability.provider_id: entry
            for entry in dependencies.provider_registry.list_catalog()
        }
        ids = request.provider_ids or tuple(available)
        return [
            {
                "provider_id": provider_id,
                "display_name": available[provider_id].capability.display_name
                if provider_id in available
                else provider_id,
                "configured": available[provider_id].configured
                if provider_id in available
                else False,
                "capabilities": list(available[provider_id].capability.capabilities)
                if provider_id in available
                else [],
                "supports_point_in_time": available[provider_id].capability.supports_point_in_time
                if provider_id in available
                else False,
                "configuration_status": "configured"
                if provider_id in available and available[provider_id].configured
                else "unconfigured",
                "check_type": "configuration_check",
                "probe_status": "not_probed",
                "check_status": "not_probed",
                "coverage": "not measured",
                "limitations": [available[provider_id].limitation]
                if provider_id in available and available[provider_id].limitation
                else ([] if provider_id in available else ["Provider is not in the catalog."]),
            }
            for provider_id in ids
        ]

    @router.post("/api/domain-plans", status_code=status.HTTP_201_CREATED)
    def generate_plan(request: DomainPlanRequest) -> DomainPlanResponse:
        if request.selection_mode == "point_in_time" and request.selection_time is None:
            raise HTTPException(
                status_code=422,
                detail="selection_time is required for point_in_time mode",
            )
        server_timestamp = request.selection_mode == "current" and request.selection_time is None
        selection_time = request.selection_time or dependencies.clock()
        spec = parse_domain_spec(
            request.description,
            regions=request.regions,
            cadence=request.cadence,
            base_currency=request.base_currency,
            selection_mode=request.selection_mode,
            selection_time=selection_time,
            target_count=request.target_count,
        )
        discovery_providers = tuple(
            dependencies.provider_registry.get(provider_id)
            for provider_id in dependencies.provider_registry.configured_provider_ids
            if "instrument_discovery"
            in dependencies.provider_registry.get(provider_id).capability.capabilities
        )
        if not discovery_providers:
            raise HTTPException(
                status_code=503,
                detail=(
                    "No configured provider supports instrument discovery. Configure a provider "
                    "with global instrument search, such as EODHD, then retry."
                ),
            )
        if request.selection_mode == "point_in_time" and not any(
            provider.capability.supports_point_in_time for provider in discovery_providers
        ):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Point-in-time selection is unavailable: no configured instrument-discovery "
                    "provider guarantees point-in-time results. Use current mode or configure "
                    "a PIT-capable provider."
                ),
            )
        candidates, coverage, discovery_yield, warnings, successful_providers = discover_candidates(
            dependencies.provider_registry,
            spec,
            provider_as_of_time=(
                datetime.max.replace(tzinfo=UTC) if server_timestamp else selection_time
            ),
            include_current_retrievals=server_timestamp,
            clock=dependencies.clock,
        )
        if server_timestamp:
            spec = spec.model_copy(update={"selection_time": dependencies.clock()})
        if not successful_providers and warnings:
            raise HTTPException(
                status_code=502,
                detail=(
                    "All configured instrument-discovery providers failed. Check provider "
                    "configuration and retry."
                ),
            )
        plan = DomainPlanner().plan(
            spec,
            candidates,
            provider_coverage=coverage,
            discovery_yield=discovery_yield,
        )
        if warnings:
            plan = plan.model_copy(update={"warnings": plan.warnings + tuple(warnings)})
        dependencies.plans[plan.plan_id] = _PlanState(plan=plan, candidates=candidates)
        return serialize_plan(plan)

    @router.post("/api/domain-plans/{plan_id}/replace")
    def replace_instrument(plan_id: str, request: ReplaceInstrumentRequest) -> DomainPlanResponse:
        state = _get_plan_state(dependencies, plan_id)
        plan = state.plan
        if plan.status == "locked":
            raise HTTPException(status_code=409, detail="locked plans cannot be changed")
        selected = {item.candidate.instrument_id: item for item in plan.recommended}
        replacement = next(
            (
                item
                for item in plan.rejected
                if item.candidate.instrument_id == request.replacement_instrument_id
                and item.reason.startswith("Not selected:")
                and item.candidate.instrument_id not in state.excluded_ids
            ),
            None,
        )
        current = selected.get(request.remove_instrument_id)
        if current is None or replacement is None:
            raise HTTPException(
                status_code=404, detail="selected or replacement instrument not found"
            )
        if (
            not replacement.candidate.available
            or replacement.candidate.relevance < DomainPlanner.minimum_relevance
        ):
            raise HTTPException(
                status_code=422,
                detail="replacement does not meet availability and relevance requirements",
            )
        state.excluded_ids.add(request.remove_instrument_id)
        state.excluded_ids.discard(request.replacement_instrument_id)
        revised = plan.model_copy(
            update={
                "recommended": tuple(
                    item
                    for item in plan.recommended
                    if item.candidate.instrument_id != request.remove_instrument_id
                ),
                "rejected": tuple(
                    item
                    for item in plan.rejected
                    if item.candidate.instrument_id != request.replacement_instrument_id
                )
                + (current.model_copy(update={"reason": "Removed by user replacement."}),),
            }
        )
        revised = revised.model_copy(
            update={
                "recommended": revised.recommended
                + (
                    replacement.model_copy(
                        update={"reason": replacement.reason + " User-selected replacement."}
                    ),
                ),
            }
        )
        state.plan = revised
        return serialize_plan(revised)

    @router.post("/api/domain-plans/{plan_id}/lock")
    def lock_plan(plan_id: str, request: LockPlanRequest) -> dict[str, Any]:
        state = _get_plan_state(dependencies, plan_id)
        plan = state.plan
        if plan.status == "locked":
            raise HTTPException(status_code=409, detail="plan is already locked")
        if len(plan.recommended) != plan.domain_spec.target_count:
            raise HTTPException(
                status_code=422, detail="plan does not contain target_count instruments"
            )
        workspace_id = str(uuid4())
        universe = plan.to_universe_spec(workspace_id)
        workspace = DomainWorkspace(
            workspace_id=workspace_id,
            name=request.workspace_name,
            domain=plan.domain_spec.normalized_domain,
            base_currency=plan.domain_spec.base_currency,
            cadence=plan.domain_spec.cadence,
            regions=plan.domain_spec.regions,
            universe_id=universe.universe_id,
            status="ready",
        )
        repository = dependencies.domain_lock_repository or cast(
            DomainLockRepository, dependencies.workspace_repository
        )
        try:
            repository.put_workspace_with_universe(workspace, universe)
        except (AttributeError, TypeError, ValueError) as error:
            raise HTTPException(
                status_code=501,
                detail=(
                    "configured product repository cannot persist the domain workspace and universe"
                ),
            ) from error
        locked = plan.model_copy(
            update={
                "status": "locked",
                "recommended": tuple(
                    item.model_copy(update={"locked": True}) for item in plan.recommended
                ),
            }
        )
        state.plan = locked
        return {"workspace": workspace, "universe": universe}

    @router.get("/api/universes/{universe_id}")
    def get_universe(universe_id: str) -> UniverseSpec:
        repository = dependencies.universe_repository or cast(
            UniverseRepository, dependencies.workspace_repository
        )
        try:
            return repository.get_universe(universe_id)
        except RepositoryNotFoundError as error:
            raise HTTPException(status_code=404, detail="universe not found") from error

    return router


def _get_plan_state(dependencies: DomainApiDependencies, plan_id: str) -> _PlanState:
    try:
        return dependencies.plans[plan_id]
    except KeyError as error:
        raise HTTPException(status_code=404, detail="domain plan not found") from error


def serialize_plan(plan: DomainPlan) -> DomainPlanResponse:
    """Flatten planner objects into the UI wire contract and percentage scores."""

    def item_response(item: Any) -> DomainPlanItemResponse:
        return DomainPlanItemResponse(
            **item.candidate.model_dump(
                include={
                    "instrument_id",
                    "symbol",
                    "exchange",
                    "country",
                    "currency",
                    "figi",
                    "provider_symbols",
                    "asset_class",
                    "company_name",
                    "concepts",
                    "sub_industry",
                    "region",
                }
            ),
            relevance_score=round(item.relevance_score * 100),
            liquidity_score=round(item.liquidity_score * 100),
            coverage_score=round(item.coverage_score * 100),
            total_score=round(item.total_score * 100),
            reason=item.reason,
            locked=item.locked,
        )

    spec = plan.domain_spec
    return DomainPlanResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        domain_spec={
            "description": spec.description,
            "normalized_domain": spec.normalized_domain,
            "expanded_concepts": list(spec.expanded_concepts),
            "regions": list(spec.regions),
            "cadence": spec.cadence,
            "base_currency": spec.base_currency,
            "target_count": spec.target_count,
        },
        selection_time=spec.selection_time,
        selection_mode=spec.selection_mode,
        selection_method=plan.selection_method,
        methodology=plan.methodology,
        provider_coverage=plan.provider_coverage,
        discovery_yield=plan.discovery_yield,
        recommended=tuple(item_response(item) for item in plan.recommended),
        rejected=tuple(item_response(item) for item in plan.rejected),
        replacement_candidates=tuple(
            item_response(item)
            for item in plan.rejected
            if item.reason.startswith("Not selected:")
            and item.candidate.instrument_id
            not in {selected.candidate.instrument_id for selected in plan.recommended}
        ),
        warnings=plan.warnings,
    )


def discover_candidates(
    registry: ProviderRegistry,
    spec: DomainSpec,
    *,
    provider_as_of_time: datetime | None = None,
    include_current_retrievals: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> tuple[tuple[DomainCandidate, ...], dict[str, float], dict[str, float], list[str], bool]:
    """Discover instruments and derive liquidity/coverage from provider histories."""

    candidates: dict[str, DomainCandidate] = {}
    coverage: dict[str, float] = {}
    discovery_yield: dict[str, float] = {}
    warnings: list[str] = []
    successful_providers = False
    query_as_of = provider_as_of_time or spec.selection_time
    for capability_obj in registry.list_capabilities():
        capability = cast(Any, capability_obj)
        if capability.provider_id not in registry.configured_provider_ids:
            coverage[capability.provider_id] = 0.0
            discovery_yield[capability.provider_id] = 0.0
    for provider_id in registry.configured_provider_ids:
        provider = registry.get(provider_id)
        capability = provider.capability
        if "instrument_discovery" not in capability.capabilities:
            coverage[capability.provider_id] = 0.0
            discovery_yield[capability.provider_id] = 0.0
            continue
        found: dict[tuple[str, str], tuple[InstrumentRecord, set[str]]] = {}
        discovery_succeeded = False
        try:
            for concept in spec.expanded_concepts:
                result = provider.discover_instruments(
                    InstrumentQuery(query=concept, as_of_time=query_as_of)
                )
                discovery_succeeded = True
                for record in result.items:
                    key = (record.exchange, record.symbol)
                    if key not in found:
                        found[key] = (record, set())
                    found[key][1].add(concept)
                if len(found) >= max(spec.target_count * 3, 30):
                    break
        except Exception:
            coverage[capability.provider_id] = 0.0
            discovery_yield[capability.provider_id] = 0.0
            warnings.append(
                f"{capability.display_name} discovery failed; results from other providers "
                "were retained. Check its configuration and retry."
            )
            if not found:
                successful_providers = successful_providers or discovery_succeeded
                continue
        else:
            successful_providers = successful_providers or discovery_succeeded
        discovery_yield[capability.provider_id] = min(
            1.0, len(found) / max(spec.target_count, len(spec.expanded_concepts), 1)
        )
        mappers = tuple(
            registry.get(mapper_id)
            for mapper_id in registry.configured_provider_ids
            if "identifier_mapping" in registry.get(mapper_id).capability.capabilities
        )
        provider_coverages: list[float] = []
        for record, matched_concepts in found.values():
            try:
                canonical = _canonical_record(mappers or (provider,), record, query_as_of)
                candidate = _candidate_from_record(
                    provider,
                    canonical,
                    matched_concepts,
                    spec,
                    query_as_of,
                    include_current_retrievals,
                    clock or (lambda: datetime.now(UTC)),
                )
            except Exception:
                warnings.append(
                    f"{capability.display_name} data enrichment failed for one or more listings; "
                    "remaining results were retained. Check provider configuration and retry."
                )
                continue
            provider_coverages.append(candidate.data_coverage)
            previous = candidates.get(candidate.instrument_id)
            if previous is None or candidate.data_coverage > previous.data_coverage:
                candidates[candidate.instrument_id] = candidate
        coverage[capability.provider_id] = (
            sum(provider_coverages) / len(provider_coverages) if provider_coverages else 0.0
        )
        successful_providers = successful_providers or bool(provider_coverages)
    return tuple(candidates.values()), coverage, discovery_yield, warnings, successful_providers


def _canonical_record(
    providers: tuple[ProviderAdapter, ...], record: InstrumentRecord, as_of_time: datetime
) -> InstrumentRecord:
    if record.figi:
        return record
    for provider in providers:
        result = provider.map_identifier(
            IdentifierMappingRequest(
                identifier_type="symbol",
                identifier_value=record.symbol,
                exchange=record.exchange,
                as_of_time=as_of_time,
            )
        )
        mappings = tuple(
            sorted((item for item in result.items if item.figi), key=lambda item: item.figi)
        )
        if mappings:
            mapping = mappings[0]
            return record.model_copy(
                update={"figi": mapping.figi, "symbol": mapping.ticker or record.symbol}
            )
    return record


def _candidate_from_record(
    provider: ProviderAdapter,
    record: InstrumentRecord,
    matched_concepts: set[str],
    spec: DomainSpec,
    provider_as_of_time: datetime,
    include_current_retrievals: bool,
    clock: Callable[[], datetime],
) -> DomainCandidate:
    instrument_id = record.figi or f"{record.exchange}:{record.symbol}"
    currency = (record.currency or spec.base_currency).upper()
    as_of = provider_as_of_time
    requested_days = 60
    retrieved_at = clock() if include_current_retrievals else spec.selection_time
    end = retrieved_at.date() if include_current_retrievals else as_of.date()
    start = end - timedelta(days=requested_days)
    bars_result = provider.historical_bars(
        HistoricalBarsRequest(
            instrument=record,
            start=start,
            end=end,
            interval="daily",
            as_of_time=as_of,
        )
    )
    fx_multiplier = Decimal("1")
    fx_coverage = 1.0
    if currency != "USD":
        fx = provider.fx_rates(
            FxRatesRequest(
                base_currency=currency,
                quote_currency="USD",
                start=start,
                end=end,
                as_of_time=as_of,
            )
        )
        valid_rates = [item for item in fx.items if item.available_at <= retrieved_at]
        fx_coverage = (
            len(valid_rates) / fx.coverage.requested_count if fx.coverage.requested_count else 0.0
        )
        if valid_rates:
            fx_multiplier = valid_rates[-1].rate
    eligible_bars = tuple(
        bar for bar in bars_result.items if bar.chronology.available_at <= retrieved_at
    )
    bar_coverage = (
        len(eligible_bars) / bars_result.coverage.requested_count
        if bars_result.coverage.requested_count
        else 0.0
    )
    dollar_volumes = [float(bar.close * bar.volume * fx_multiplier) for bar in eligible_bars]
    avg_dollar_volume = sum(dollar_volumes) / len(dollar_volumes) if dollar_volumes else 0.0
    coverage = min(bar_coverage, fx_coverage) if currency != "USD" else bar_coverage
    normalized = spec.normalized_domain
    names = set(record.name.casefold().replace("-", " ").split())
    concept_tokens = set(" ".join(matched_concepts).casefold().split())
    relevance = min(
        1.0, 0.65 + 0.25 * (len(names & concept_tokens) > 0) + 0.10 * bool(matched_concepts)
    )
    if record.asset_class == "adr":
        asset_class: Literal["equity", "adr", "etf"] = "adr"
    elif record.asset_class == "etf":
        asset_class = "etf"
    else:
        asset_class = "equity"
    return DomainCandidate(
        instrument_id=instrument_id,
        symbol=record.symbol,
        exchange=record.exchange,
        country=record.country or "Unknown",
        currency=currency,
        figi=record.figi,
        provider_symbols={provider.capability.provider_id: record.provider_symbol or record.symbol},
        asset_class=asset_class,
        company_name=record.name or record.symbol,
        concepts=tuple(sorted(matched_concepts)),
        sub_industry=_sub_industry(normalized, matched_concepts),
        region=_region(record.country),
        relevance=relevance,
        average_daily_value_usd=avg_dollar_volume,
        data_coverage=coverage,
        available=bool(record.symbol and record.exchange),
        canonical_id_resolved=record.figi is not None,
        point_in_time_verified=provider.capability.supports_point_in_time,
        ambiguity_group=record.name.casefold() or f"{record.exchange}:{record.symbol}",
        resolution_rank=1 if record.figi else 2,
    )


def _sub_industry(domain: str, concepts: set[str]) -> str:
    for candidate in sorted(concepts):
        normalized = candidate.casefold()
        if any(word in normalized for word in ("equipment", "lithography", "deposition", "etch")):
            return "equipment"
        if any(word in normalized for word in ("foundry", "fabrication")):
            return "foundry"
        if "memory" in normalized:
            return "memory"
        if any(word in normalized for word in ("packaging", "testing")):
            return "packaging and testing"
        if any(word in normalized for word in ("material", "wafer")):
            return "materials"
    return domain


def _region(country: str | None) -> str:
    code = (country or "").casefold()
    if code in {"us", "ca", "mx", "br", "ar"}:
        return "Americas"
    if code in {"nl", "de", "fr", "gb", "uk", "it", "ch", "se", "fi"}:
        return "Europe"
    if code:
        return "Asia"
    return "Unknown"
