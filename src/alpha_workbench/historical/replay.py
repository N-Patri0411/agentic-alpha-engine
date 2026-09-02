"""Snapshot selection and write-once replay services."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ..graph_registry import GraphSnapshot, RippleRiskScorer
from .records import HistoricalEvent, HistoricalScenarioRun


class SnapshotTimeline:
    """Loads graph snapshots and chooses the newest version known at an as-of time."""

    def __init__(self, snapshots_directory: Path) -> None:
        self._directory = snapshots_directory

    def select_as_of(self, as_of_time: datetime) -> tuple[Path, GraphSnapshot]:
        if as_of_time.tzinfo is None:
            raise ValueError("as_of_time must include a timezone")
        candidates: list[tuple[Path, GraphSnapshot]] = []
        for path in sorted(self._directory.glob("*.json")):
            snapshot = GraphSnapshot.from_json(path)
            if snapshot.created_at <= as_of_time:
                candidates.append((path, snapshot))
        if not candidates:
            raise LookupError("no graph snapshot was available at the requested as-of time")
        return max(
            candidates, key=lambda candidate: (candidate[1].created_at, candidate[1].snapshot_id)
        )


class ScenarioRunStore:
    """Persists each scenario-run receipt as a write-once JSON artifact."""

    def publish_new(self, path: Path, run: HistoricalScenarioRun) -> None:
        if path.exists():
            raise FileExistsError(f"refusing to overwrite immutable scenario run: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(run.model_dump_json(indent=2), encoding="utf-8")


class HistoricalScenarioReplayer:
    """Replays a sourced event using only a graph snapshot available then."""

    def __init__(self, timeline: SnapshotTimeline, store: ScenarioRunStore) -> None:
        self._timeline = timeline
        self._store = store

    def replay(
        self,
        *,
        event: HistoricalEvent,
        as_of_time: datetime,
        run_path: Path,
        max_hops: int = 3,
    ) -> HistoricalScenarioRun:
        if event.available_at > as_of_time:
            raise ValueError("event evidence was unavailable at the requested replay time")
        snapshot_path, snapshot = self._timeline.select_as_of(as_of_time)
        result = RippleRiskScorer(snapshot).score(
            shock_entity_id=event.shock_entity_id,
            severity=event.shock_severity,
            as_of_time=as_of_time,
            max_hops=max_hops,
        )
        run = HistoricalScenarioRun(
            event=event,
            graph_snapshot_id=snapshot.snapshot_id,
            graph_snapshot_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            as_of_time=as_of_time,
            created_at=datetime.now(UTC),
            result=result,
        )
        self._store.publish_new(run_path, run)
        return run
