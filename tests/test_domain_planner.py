from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.agents.domain_agent import DomainAgent
from alpha_workbench.agents.universe_agent import UniverseAgent
from alpha_workbench.domain import DomainCandidate

FIXTURE = (
    Path(__file__).parent / "fixtures" / "domain" / "semiconductor_manufacturing_candidates.json"
)


def candidates() -> tuple[DomainCandidate, ...]:
    values = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return tuple(DomainCandidate.model_validate(item) for item in values)


def test_semiconductor_manufacturing_recommends_ten_explained_global_instruments() -> None:
    selected_at = datetime(2026, 9, 30, 14, tzinfo=UTC)
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        regions=("global",),
        selection_mode="current",
        selection_time=selected_at,
        target_count=10,
    )
    plan = UniverseAgent().recommend(spec, candidates(), provider_coverage={"fixture": 1.0})

    assert plan.status == "ready"
    assert len(plan.recommended) == 10
    assert len({item.candidate.instrument_id for item in plan.recommended}) == 10
    assert {item.candidate.region for item in plan.recommended} >= {"Asia", "Europe", "Americas"}
    assert all(
        item.reason and item.candidate.figi and item.candidate.exchange for item in plan.recommended
    )
    assert "lithography" in spec.expanded_concepts
    assert plan.domain_spec.selection_time == selected_at
    assert plan.domain_spec.selection_mode == "current"
    assert plan.selection_method
    assert any("unavailable" in item.reason for item in plan.rejected)
    assert any("below the 0.35" in item.reason for item in plan.rejected)
    assert any(
        item.candidate.symbol == "TSM" and item.candidate.exchange == "XNAS"
        for item in plan.rejected
    )


def test_locked_universe_retains_selection_metadata_and_canonical_refs() -> None:
    selected_at = datetime(2026, 9, 30, tzinfo=UTC)
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        selection_time=selected_at,
        selection_mode="current",
    )
    plan = UniverseAgent().recommend(spec, candidates())
    universe = plan.to_universe_spec("workspace-1", universe_id="universe-1")

    assert universe.workspace_id == "workspace-1"
    assert universe.selection_time == selected_at
    assert universe.selection_mode == "current"
    assert universe.selection_method == plan.selection_method
    assert len(universe.instruments) == 10
    assert {instrument.exchange for instrument in universe.instruments}


def test_point_in_time_excludes_instruments_without_historical_listing_dates() -> None:
    selected_at = datetime(2020, 1, 1, tzinfo=UTC)
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        selection_mode="point_in_time",
        selection_time=selected_at,
    )
    plan = UniverseAgent().recommend(spec, candidates())

    assert plan.status == "insufficient_candidates"
    assert not plan.recommended
    assert len(plan.rejected) == len(candidates())
    assert all(
        "listing activity" in item.reason
        for item in plan.rejected
        if item.candidate.available and item.candidate.relevance >= 0.35
    )


def test_requested_regions_filter_out_nonmatching_candidates() -> None:
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        regions=("Asia",),
        selection_time=datetime(2026, 9, 30, tzinfo=UTC),
        target_count=3,
    )
    plan = UniverseAgent().recommend(spec, candidates())

    assert len(plan.recommended) == 3
    assert {item.candidate.region for item in plan.recommended} == {"Asia"}
    assert any("outside the requested regions" in item.reason for item in plan.rejected)


def test_requested_country_code_matches_instrument_country() -> None:
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        regions=("NL",),
        selection_time=datetime(2026, 9, 30, tzinfo=UTC),
        target_count=1,
    )
    plan = UniverseAgent().recommend(spec, candidates())

    assert len(plan.recommended) == 1
    assert plan.recommended[0].candidate.country == "NL"


def test_diversity_bonus_can_prefer_a_slightly_lower_scoring_candidate() -> None:
    spec = DomainAgent().interpret(
        "semiconductor manufacturing",
        selection_time=datetime(2026, 9, 30, tzinfo=UTC),
        target_count=2,
    )
    first, second = candidates()[:2]
    concentrated = first.model_copy(
        update={"sub_industry": "equipment", "region": "Asia", "relevance": 0.95}
    )
    diverse = second.model_copy(
        update={"sub_industry": "foundry", "region": "Europe", "relevance": 0.85}
    )
    plan = UniverseAgent().recommend(spec, (concentrated, diverse))

    assert len(plan.recommended) == 2
    assert plan.recommended[0].candidate.instrument_id == concentrated.instrument_id
    assert plan.recommended[1].candidate.instrument_id == diverse.instrument_id
    assert plan.recommended[0].total_score > plan.recommended[1].total_score
