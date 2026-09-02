from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from alpha_workbench.graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot
from alpha_workbench.historical import (
    HistoricalEvent,
    HistoricalScenarioReplayer,
    ScenarioEvidence,
    ScenarioRunStore,
    SnapshotTimeline,
    build_scenario_graph_view,
)

REGISTRY = Path("data/entities/semiconductor_v1.json")
SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
EVENT_TIME = datetime(2026, 5, 1, tzinfo=UTC)


def _event(*, available_at: datetime = EVENT_TIME) -> HistoricalEvent:
    return HistoricalEvent(
        event_id="fixture-tsm-capacity-event",
        title="Fixture TSM capacity disruption",
        event_kind="capacity_disruption",
        description="A bounded fixture event used to prove point-in-time replay.",
        shock_entity_id="TSM",
        shock_severity=0.9,
        observed_at=EVENT_TIME - timedelta(hours=1),
        available_at=available_at,
        evidence=[
            ScenarioEvidence(
                observation_id=uuid4(),
                source_url="https://example.test/event",
                content_sha256="e" * 64,
            )
        ],
    )


def _timeline(tmp_path: Path) -> tuple[SnapshotTimeline, GraphSnapshot]:
    registry = EntityRegistry.from_json(REGISTRY)
    publisher = GraphPublisher(registry)
    base = GraphSnapshot.from_json(SNAPSHOT)
    directory = tmp_path / "snapshots"
    early = publisher.build_snapshot(
        snapshot_id="fixture-early",
        created_at=EVENT_TIME - timedelta(days=2),
        edges=base.edges,
    )
    late = publisher.build_snapshot(
        snapshot_id="fixture-late",
        created_at=EVENT_TIME + timedelta(days=1),
        edges=base.edges,
    )
    publisher.publish_new(directory / "early.json", early)
    publisher.publish_new(directory / "late.json", late)
    return SnapshotTimeline(directory), early


def test_replay_selects_only_snapshot_known_at_event_time_and_is_write_once(tmp_path: Path) -> None:
    timeline, early = _timeline(tmp_path)
    event = _event()
    run_path = tmp_path / "runs" / "fixture-run.json"
    run = HistoricalScenarioReplayer(timeline, ScenarioRunStore()).replay(
        event=event, as_of_time=EVENT_TIME, run_path=run_path
    )

    assert run.graph_snapshot_id == early.snapshot_id
    assert run_path.exists()
    with pytest.raises(FileExistsError):
        HistoricalScenarioReplayer(timeline, ScenarioRunStore()).replay(
            event=event, as_of_time=EVENT_TIME, run_path=run_path
        )


def test_replay_rejects_event_evidence_that_was_not_available_yet(tmp_path: Path) -> None:
    timeline, _ = _timeline(tmp_path)
    event = _event(available_at=EVENT_TIME + timedelta(minutes=1))

    with pytest.raises(ValueError, match="unavailable"):
        HistoricalScenarioReplayer(timeline, ScenarioRunStore()).replay(
            event=event, as_of_time=EVENT_TIME, run_path=tmp_path / "run.json"
        )


def test_graph_view_exposes_snapshot_edges_and_scenario_severity(tmp_path: Path) -> None:
    timeline, early = _timeline(tmp_path)
    event = _event()
    run = HistoricalScenarioReplayer(timeline, ScenarioRunStore()).replay(
        event=event, as_of_time=EVENT_TIME, run_path=tmp_path / "run.json"
    )

    view = build_scenario_graph_view(
        registry=EntityRegistry.from_json(REGISTRY), snapshot=early, scenario=run.result
    )

    nodes = {node.id: node for node in view.nodes}
    assert nodes["TSM"].severity == 0.9
    assert nodes["NVDA"].severity == pytest.approx(0.9 * 0.75 * 0.65)
    assert any(edge.source == "TSM" and edge.target == "NVDA" for edge in view.edges)
