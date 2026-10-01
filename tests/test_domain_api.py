from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alpha_workbench.domain import DomainCandidate, DomainPlanner, parse_domain_spec
from alpha_workbench.persistence.repositories import (
    ImmutableVersionError,
    InMemoryVersionedRepository,
    RepositoryNotFoundError,
)
from alpha_workbench.product import DomainWorkspace, UniverseSpec
from alpha_workbench.providers.contracts import (
    CoverageReport,
    DataChronology,
    DiscoveryResult,
    HistoricalBar,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    InstrumentQuery,
    InstrumentRecord,
    ProviderBudget,
    ProviderCapability,
    ProviderProvenance,
)
from alpha_workbench.providers.registry import ProviderRegistry
from alpha_workbench.server.domain_api import (
    DomainApiDependencies,
    _PlanState,
    create_domain_router,
    discover_candidates,
    serialize_plan,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "domain" / "semiconductor_manufacturing_candidates.json"
)


class EmptyDiscoveryProvider:
    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="fixture-empty",
            display_name="Empty fixture",
            capabilities=("instrument_discovery",),
        )

    @property
    def budget(self) -> ProviderBudget:
        return ProviderBudget()

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        return DiscoveryResult(
            items=(),
            coverage=CoverageReport(
                capability="instrument_discovery",
                status="missing",
                requested_count=1,
                missing_identifiers=(request.query,),
            ),
            provenance=ProviderProvenance(
                provider_id=self.capability.provider_id,
                request_id=str(uuid4()),
                retrieved_at=datetime.now(UTC),
            ),
            as_of_time=request.as_of_time,
        )


class FailingDiscoveryProvider(EmptyDiscoveryProvider):
    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="fixture-failing",
            display_name="Failing fixture",
            capabilities=("instrument_discovery",),
        )

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        del request
        raise RuntimeError("secret=never-return-this")


class DiscoveryOnlyProvider(EmptyDiscoveryProvider):
    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        del request
        instrument = InstrumentRecord(
            symbol="ONLY", exchange="XNAS", name="Discovery-only company", figi="BBG000ONLY01"
        )
        return DiscoveryResult(
            items=(instrument,),
            coverage=CoverageReport(
                capability="instrument_discovery",
                status="complete",
                requested_count=1,
                returned_count=1,
            ),
            provenance=ProviderProvenance(
                provider_id=self.capability.provider_id,
                request_id=str(uuid4()),
                retrieved_at=datetime.now(UTC),
            ),
            as_of_time=datetime.now(UTC),
        )


class TimedDiscoveryProvider(EmptyDiscoveryProvider):
    retrieved_at = datetime(2026, 9, 30, 14, 0, 1, tzinfo=UTC)

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider_id="fixture-timed",
            display_name="Timed fixture",
            capabilities=("instrument_discovery", "historical_bars"),
            supports_point_in_time=True,
        )

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        from alpha_workbench.providers.contracts import InstrumentRecord

        items = ()
        if request.as_of_time >= self.retrieved_at:
            items = (
                InstrumentRecord(
                    symbol="TEST",
                    exchange="XNAS",
                    name="Test Semiconductor Maker",
                    figi="BBG000TEST01",
                    currency="USD",
                    country="US",
                ),
            )
        return DiscoveryResult(
            items=items,
            coverage=CoverageReport(
                capability="instrument_discovery",
                status="complete" if items else "missing",
                requested_count=1,
                returned_count=len(items),
                missing_identifiers=() if items else (request.query,),
            ),
            provenance=ProviderProvenance(
                provider_id=self.capability.provider_id,
                request_id=str(uuid4()),
                retrieved_at=self.retrieved_at,
            ),
            as_of_time=request.as_of_time,
        )

    def historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult:
        instant = self.retrieved_at
        bar_start = datetime.combine(date(2026, 9, 29), datetime.min.time(), tzinfo=UTC)
        bar_end = bar_start + timedelta(days=1)
        item = HistoricalBar(
            instrument=request.instrument,
            start=bar_start,
            end=bar_end,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000000"),
            chronology=DataChronology(
                observed_at=instant,
                available_at=instant,
                as_of_time=request.as_of_time,
            ),
        )
        return HistoricalBarsResult(
            items=(item,),
            coverage=CoverageReport(
                capability="historical_bars",
                status="complete",
                requested_count=1,
                returned_count=1,
            ),
            provenance=ProviderProvenance(
                provider_id=self.capability.provider_id,
                request_id=str(uuid4()),
                retrieved_at=instant,
            ),
            as_of_time=request.as_of_time,
        )


def domain_candidates() -> tuple[DomainCandidate, ...]:
    values = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return tuple(DomainCandidate.model_validate(item) for item in values)


def test_discovery_yield_is_not_reported_as_historical_data_coverage() -> None:
    spec = parse_domain_spec(
        "semiconductor manufacturing", selection_time=datetime(2026, 9, 30, tzinfo=UTC)
    )
    _, provider_coverage, discovery_yield, _, _ = discover_candidates(
        ProviderRegistry((DiscoveryOnlyProvider(),)), spec
    )

    assert provider_coverage["fixture-empty"] == 0.0
    assert 0.0 < discovery_yield["fixture-empty"] < 1.0


def test_plan_serializer_matches_flat_api_wire_contract() -> None:
    spec = parse_domain_spec(
        "semiconductor manufacturing",
        selection_time=datetime(2026, 9, 30, tzinfo=UTC),
    )
    plan = DomainPlanner().plan(spec, domain_candidates())

    response = serialize_plan(plan)
    payload = json.loads(response.model_dump_json())

    assert set(payload) == {
        "plan_id",
        "status",
        "domain_spec",
        "selection_time",
        "selection_mode",
        "selection_method",
        "methodology",
        "provider_coverage",
        "discovery_yield",
        "recommended",
        "rejected",
        "replacement_candidates",
        "warnings",
    }
    assert "expanded_concepts" in payload["domain_spec"]
    assert len(payload["recommended"]) == 10
    assert payload["recommended"][0]["total_score"] <= 100
    assert "candidate" not in payload["recommended"][0]
    assert payload["replacement_candidates"]


def test_two_sequential_replacements_and_lock_persist_workspace_and_universe() -> None:
    spec = parse_domain_spec(
        "semiconductor manufacturing",
        selection_time=datetime(2026, 9, 30, tzinfo=UTC),
    )
    candidates = domain_candidates()
    plan = DomainPlanner().plan(spec, candidates)
    workspace_repository = InMemoryVersionedRepository()
    dependencies = DomainApiDependencies(ProviderRegistry(), workspace_repository)
    dependencies.plans[plan.plan_id] = _PlanState(plan, candidates)
    app = FastAPI()
    app.include_router(create_domain_router(dependencies))
    client = TestClient(app)

    initial_id = plan.recommended[0].candidate.instrument_id
    first_replacement = next(
        item.candidate.instrument_id
        for item in plan.rejected
        if item.reason.startswith("Not selected:")
    )
    first = client.post(
        f"/api/domain-plans/{plan.plan_id}/replace",
        json={
            "remove_instrument_id": initial_id,
            "replacement_instrument_id": first_replacement,
        },
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_replacement in {item["instrument_id"] for item in first_body["recommended"]}

    second_alternative = next(
        item["instrument_id"]
        for item in first_body["replacement_candidates"]
        if item["instrument_id"] != first_replacement
    )
    second_remove = next(
        item["instrument_id"]
        for item in first_body["recommended"]
        if item["instrument_id"] != first_replacement
    )
    second = client.post(
        f"/api/domain-plans/{plan.plan_id}/replace",
        json={
            "remove_instrument_id": second_remove,
            "replacement_instrument_id": second_alternative,
        },
    )
    assert second.status_code == 200
    assert second_alternative in {item["instrument_id"] for item in second.json()["recommended"]}

    locked = client.post(
        f"/api/domain-plans/{plan.plan_id}/lock",
        json={"workspace_name": "Semiconductor manufacturing"},
    )
    assert locked.status_code == 200
    assert set(locked.json()) == {"workspace", "universe"}
    workspace = DomainWorkspace.model_validate(locked.json()["workspace"])
    universe = UniverseSpec.model_validate(locked.json()["universe"])
    assert workspace.universe_id == universe.universe_id
    assert len(universe.instruments) == 10
    assert workspace_repository.get(DomainWorkspace, workspace.workspace_id) == workspace
    assert workspace_repository.get(UniverseSpec, universe.universe_id) == universe
    fetched = client.get(f"/api/universes/{universe.universe_id}")
    assert fetched.status_code == 200
    assert UniverseSpec.model_validate(fetched.json()) == universe


def test_in_memory_lock_is_rollback_safe_when_workspace_conflicts() -> None:
    repository = InMemoryVersionedRepository()
    existing = DomainWorkspace(
        workspace_id="w-conflict",
        name="Existing",
        domain="semiconductors",
    )
    repository.put(existing)
    conflicting = existing.model_copy(update={"name": "Different"})
    universe = DomainPlanner().plan(
        parse_domain_spec("semiconductor manufacturing", selection_time=datetime.now(UTC)),
        domain_candidates(),
    ).to_universe_spec("w-conflict")

    try:
        repository.put_workspace_with_universe(conflicting, universe)
    except ImmutableVersionError:
        pass
    else:
        raise AssertionError("conflicting workspace version should be rejected")
    try:
        repository.get_universe(universe.universe_id)
    except RepositoryNotFoundError:
        pass
    else:
        raise AssertionError("universe write should roll back with the workspace conflict")


def test_current_mode_gets_timestamp_and_point_in_time_requires_one() -> None:
    dependencies = DomainApiDependencies(
        ProviderRegistry((EmptyDiscoveryProvider(),)), InMemoryVersionedRepository()
    )
    app = FastAPI()
    app.include_router(create_domain_router(dependencies))
    client = TestClient(app)

    current = client.post(
        "/api/domain-plans",
        json={"description": "semiconductor manufacturing", "selection_mode": "current"},
    )
    assert current.status_code == 201
    assert current.json()["selection_time"]
    assert current.json()["selection_mode"] == "current"
    assert current.json()["status"] == "insufficient_candidates"

    historical = client.post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "selection_mode": "point_in_time",
        },
    )
    assert historical.status_code == 422

    naive = client.post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "selection_time": "2026-09-30T00:00:00",
        },
    )
    assert naive.status_code == 422


def test_domain_plan_returns_actionable_error_without_discovery_provider() -> None:
    dependencies = DomainApiDependencies(ProviderRegistry(), InMemoryVersionedRepository())
    app = FastAPI()
    app.include_router(create_domain_router(dependencies))
    response = TestClient(app).post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "selection_time": "2026-09-30T00:00:00Z",
        },
    )

    assert response.status_code == 503
    assert "Configure a provider" in response.json()["detail"]

    pit_dependencies = DomainApiDependencies(
        ProviderRegistry((EmptyDiscoveryProvider(),)), InMemoryVersionedRepository()
    )
    pit_app = FastAPI()
    pit_app.include_router(create_domain_router(pit_dependencies))
    pit = TestClient(pit_app).post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "selection_mode": "point_in_time",
            "selection_time": "2026-09-30T00:00:00Z",
        },
    )
    assert pit.status_code == 503
    assert "PIT-capable" in pit.json()["detail"]


def test_server_current_selection_includes_just_retrieved_data_but_pit_does_not() -> None:
    initial = datetime(2026, 9, 30, 14, 0, 0, tzinfo=UTC)
    TimedDiscoveryProvider.retrieved_at = initial + timedelta(minutes=10)
    clock_values = iter(
        (
            initial,
            initial + timedelta(minutes=11),
            initial + timedelta(minutes=12),
        )
    )
    current_dependencies = DomainApiDependencies(
        ProviderRegistry((TimedDiscoveryProvider(),)),
        InMemoryVersionedRepository(),
        clock=lambda: next(clock_values),
    )
    current_app = FastAPI()
    current_app.include_router(create_domain_router(current_dependencies))
    current = TestClient(current_app).post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "target_count": 1,
            "selection_mode": "current",
        },
    )

    assert current.status_code == 201
    assert current.json()["status"] == "ready"
    completed_at = (initial + timedelta(minutes=12)).isoformat().replace("+00:00", "Z")
    assert current.json()["selection_time"] == completed_at
    assert current.json()["recommended"][0]["coverage_score"] == 100

    past_dependencies = DomainApiDependencies(
        ProviderRegistry((TimedDiscoveryProvider(),)), InMemoryVersionedRepository()
    )
    past_app = FastAPI()
    past_app.include_router(create_domain_router(past_dependencies))
    past = TestClient(past_app).post(
        "/api/domain-plans",
        json={
            "description": "semiconductor manufacturing",
            "target_count": 1,
            "selection_mode": "point_in_time",
            "selection_time": initial.isoformat(),
        },
    )

    assert past.status_code == 201
    assert past.json()["status"] == "insufficient_candidates"
    assert past.json()["recommended"] == []


def test_provider_capabilities_and_check_keep_unconfigured_catalog_entries_visible(
    monkeypatch,
) -> None:
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    registry = ProviderRegistry.from_config()
    dependencies = DomainApiDependencies(registry, InMemoryVersionedRepository())
    app = FastAPI()
    app.include_router(create_domain_router(dependencies))
    client = TestClient(app)

    capabilities = {
        item["provider_id"]: item for item in client.get("/api/providers/capabilities").json()
    }
    assert {"openfigi", "eodhd", "alpha_vantage_compat"} <= set(capabilities)
    assert capabilities["eodhd"]["configured"] is False
    check = client.post("/api/providers/check", json={"provider_ids": ["eodhd"]})
    assert check.json()[0]["configured"] is False
    assert check.json()[0]["configuration_status"] == "unconfigured"
    assert check.json()[0]["check_type"] == "configuration_check"
    assert check.json()[0]["probe_status"] == "not_probed"
    assert "EODHD_API_KEY" not in json.dumps(check.json())
    too_many = client.post("/api/providers/check", json={"provider_ids": ["x"] * 33})
    assert too_many.status_code == 422


def test_provider_failure_is_safe_and_partial_discovery_is_preserved() -> None:
    repository = InMemoryVersionedRepository()
    dependencies = DomainApiDependencies(
        ProviderRegistry((FailingDiscoveryProvider(), EmptyDiscoveryProvider())), repository
    )
    app = FastAPI()
    app.include_router(create_domain_router(dependencies))
    client = TestClient(app)
    response = client.post(
        "/api/domain-plans",
        json={"description": "semiconductor manufacturing", "target_count": 1},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "insufficient_candidates"
    assert any(
        "Failing fixture discovery failed" in warning
        for warning in response.json()["warnings"]
    )
    assert "never-return-this" not in response.text

    only_failure = DomainApiDependencies(
        ProviderRegistry((FailingDiscoveryProvider(),)), repository
    )
    app = FastAPI()
    app.include_router(create_domain_router(only_failure))
    failed = TestClient(app).post(
        "/api/domain-plans",
        json={"description": "semiconductor manufacturing", "target_count": 1},
    )
    assert failed.status_code == 502
    assert "never-return-this" not in failed.text
