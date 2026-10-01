from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from alpha_workbench.persistence import ImmutableVersionError, InMemoryVersionedRepository
from alpha_workbench.product import (
    DomainWorkspace,
    InstrumentRef,
    ReadinessCheck,
    ReadinessReport,
    StrategySpec,
    UniverseSpec,
)

WHEN = datetime(2024, 1, 2, 12, tzinfo=UTC)


def instrument(symbol: str, number: int) -> InstrumentRef:
    return InstrumentRef(
        instrument_id=f"XNYS:{symbol}",
        symbol=symbol,
        exchange="XNYS",
        currency="USD",
        entity_id=f"entity-{number}",
    )


def test_universe_requires_selection_time_and_mode() -> None:
    with pytest.raises(ValidationError):
        UniverseSpec(
            universe_id="u-1",
            workspace_id="w-1",
            domain="semiconductor manufacturing",
            instruments=(instrument("AMD", 1),),
            selection_method="test",
            selection_mode="current",
        )

    with pytest.raises(ValidationError):
        UniverseSpec(
            universe_id="u-1",
            workspace_id="w-1",
            domain="semiconductor manufacturing",
            instruments=(instrument("AMD", 1),),
            selection_time=WHEN,
            selection_method="test",
        )


def test_contract_canonical_json_is_deterministic() -> None:
    first = DomainWorkspace(
        workspace_id="w-1",
        name="Semis",
        domain="semiconductor manufacturing",
        created_at=WHEN,
        regions=("US", "TW"),
    )
    second = DomainWorkspace.model_validate(first.model_dump())
    assert first.canonical_json() == second.canonical_json()
    assert first.content_sha256() == second.content_sha256()
    assert first.version_key == "w-1:v1"

    with pytest.raises(ValidationError):
        first.version = 2  # type: ignore[misc]


def test_universe_rejects_duplicate_instruments_and_invalid_timezone() -> None:
    with pytest.raises(ValidationError):
        UniverseSpec(
            universe_id="u-1",
            workspace_id="w-1",
            domain="semiconductors",
            instruments=(instrument("AMD", 1), instrument("AMD", 1)),
            selection_time=WHEN,
            selection_mode="point_in_time",
            selection_method="ranked",
        )
    with pytest.raises(ValidationError):
        UniverseSpec(
            universe_id="u-2",
            workspace_id="w-1",
            domain="semiconductors",
            instruments=(instrument("AMD", 1),),
            selection_time=datetime(2024, 1, 2),
            selection_mode="point_in_time",
            selection_method="ranked",
        )


def test_readiness_status_is_derived_from_checks() -> None:
    with pytest.raises(ValidationError):
        ReadinessReport(
            readiness_id="r-1",
            workspace_id="w-1",
            status="ready",
            checks=(ReadinessCheck(name="provider", status="fail"),),
        )
    report = ReadinessReport(
        readiness_id="r-2",
        workspace_id="w-1",
        status="degraded",
        checks=(ReadinessCheck(name="provider", status="warn"),),
    )
    assert not report.is_ready


def test_in_memory_repository_is_append_only_and_idempotent() -> None:
    repository: InMemoryVersionedRepository[DomainWorkspace] = InMemoryVersionedRepository()
    workspace = DomainWorkspace(
        workspace_id="w-1",
        name="Semis",
        domain="semiconductor manufacturing",
        created_at=WHEN,
    )
    assert repository.put(workspace) == workspace
    assert repository.put(workspace) == workspace

    changed = workspace.model_copy(update={"name": "Semis revised"})
    with pytest.raises(ImmutableVersionError):
        repository.put(changed)
    version_two = workspace.model_copy(update={"version": 2, "name": "Semis revised"})
    assert repository.put(version_two).version == 2
    assert [item.version for item in repository.list_versions(DomainWorkspace, "w-1")] == [1, 2]


def test_in_memory_universe_is_keyed_by_universe_id() -> None:
    repository: InMemoryVersionedRepository[UniverseSpec] = InMemoryVersionedRepository()
    universe = UniverseSpec(
        universe_id="u-1",
        workspace_id="w-1",
        domain="semiconductors",
        instruments=(instrument("AMD", 1),),
        selection_time=WHEN,
        selection_mode="current",
        selection_method="fixture",
    )

    repository.put(universe)

    assert repository.get(UniverseSpec, "u-1") == universe


def test_strategy_contract_has_executable_shape() -> None:
    strategy = StrategySpec(
        strategy_id="s-1",
        workspace_id="w-1",
        name="Neighbour momentum",
        universe_id="u-1",
        signal_expression="Rank(price_return_20d)",
        feature_names=("price_return_20d",),
        created_at=WHEN,
    )
    assert strategy.canonical_json().startswith("{")
