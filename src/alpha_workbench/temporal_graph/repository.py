"""Append-only repositories and deterministic comparison for temporal graphs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from pydantic import TypeAdapter

from alpha_workbench.product.canonical import canonical_json

from .contracts import (
    GraphPublicationReceipt,
    GraphSnapshotDiff,
    TemporalGraphSnapshot,
)


def _replay_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("replay timestamps must be timezone-aware")
    return value


class GraphSnapshotNotFoundError(KeyError):
    """Raised when a graph snapshot cannot be found."""


class ImmutableGraphSnapshotError(ValueError):
    """Raised when an existing snapshot ID is reused for different content."""


class TemporalGraphRepository(Protocol):
    """Persistence boundary for full, immutable temporal graph snapshots."""

    def latest(self, workspace_id: str) -> TemporalGraphSnapshot: ...

    def get(self, snapshot_id: str) -> TemporalGraphSnapshot: ...

    def list(self, workspace_id: str) -> list[TemporalGraphSnapshot]: ...

    def publish(self, snapshot: TemporalGraphSnapshot) -> GraphPublicationReceipt: ...

    def replay(
        self, workspace_id: str, *, as_of_time: datetime, knowledge_time: datetime
    ) -> TemporalGraphSnapshot: ...


def _receipt(snapshot: TemporalGraphSnapshot) -> GraphPublicationReceipt:
    return GraphPublicationReceipt(
        snapshot_id=snapshot.snapshot_id,
        workspace_id=snapshot.workspace_id,
        content_digest=snapshot.content_sha256(),
        published_at=snapshot.published_at,
    )


def diff_snapshots(
    prior: TemporalGraphSnapshot, current: TemporalGraphSnapshot
) -> GraphSnapshotDiff:
    """Compare two snapshots by stable IDs, returning alphabetically ordered IDs."""

    def changed(
        old: tuple[Any, ...], new: tuple[Any, ...], key: str
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        old_by_id = {getattr(item, key): item for item in old}
        new_by_id = {getattr(item, key): item for item in new}
        old_ids, new_ids = set(old_by_id), set(new_by_id)
        added = tuple(sorted(new_ids - old_ids))
        removed = tuple(sorted(old_ids - new_ids))
        updated = tuple(
            sorted(
                item_id
                for item_id in old_ids & new_ids
                if old_by_id[item_id].content_sha256() != new_by_id[item_id].content_sha256()
            )
        )
        return added, removed, updated

    an, rn, cn = changed(prior.nodes, current.nodes, "node_id")
    ar, rr, cr = changed(prior.relationships, current.relationships, "relationship_id")
    ae, re, ce = changed(prior.edge_states, current.edge_states, "edge_id")
    return GraphSnapshotDiff(
        created_at=current.published_at,
        prior_snapshot_id=prior.snapshot_id,
        current_snapshot_id=current.snapshot_id,
        prior_universe_id=prior.universe_id,
        current_universe_id=current.universe_id,
        added_universe_instrument_ids=tuple(
            sorted(set(current.universe_instrument_ids) - set(prior.universe_instrument_ids))
        ),
        removed_universe_instrument_ids=tuple(
            sorted(set(prior.universe_instrument_ids) - set(current.universe_instrument_ids))
        ),
        added_node_ids=an,
        removed_node_ids=rn,
        changed_node_ids=cn,
        added_relationship_ids=ar,
        removed_relationship_ids=rr,
        changed_relationship_ids=cr,
        added_edge_ids=ae,
        removed_edge_ids=re,
        changed_edge_ids=ce,
    )


class InMemoryTemporalGraphRepository:
    """Test/development repository with append-only snapshot semantics."""

    def __init__(self) -> None:
        self._snapshots: dict[str, TemporalGraphSnapshot] = {}

    def publish(self, snapshot: TemporalGraphSnapshot) -> GraphPublicationReceipt:
        existing = self._snapshots.get(snapshot.snapshot_id)
        if existing is not None:
            if existing.content_sha256() != snapshot.content_sha256():
                raise ImmutableGraphSnapshotError(f"snapshot {snapshot.snapshot_id!r} is immutable")
            return _receipt(existing)
        self._snapshots[snapshot.snapshot_id] = snapshot
        return _receipt(snapshot)

    def get(self, snapshot_id: str) -> TemporalGraphSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise GraphSnapshotNotFoundError(snapshot_id) from exc

    def list(self, workspace_id: str) -> list[TemporalGraphSnapshot]:
        return sorted(
            (item for item in self._snapshots.values() if item.workspace_id == workspace_id),
            key=lambda item: (item.published_at, item.snapshot_id),
        )

    def latest(self, workspace_id: str) -> TemporalGraphSnapshot:
        snapshots = self.list(workspace_id)
        if not snapshots:
            raise GraphSnapshotNotFoundError(workspace_id)
        return snapshots[-1]

    def replay(
        self, workspace_id: str, *, as_of_time: datetime, knowledge_time: datetime
    ) -> TemporalGraphSnapshot:
        """Select latest known immutable snapshot, then filter its bitemporal edges.

        The returned value is a derived snapshot with the requested clocks. Stored
        snapshots are never edited, and assertions learned after knowledge_time
        cannot participate in the replay.
        """
        as_of_time, knowledge_time = _replay_time(as_of_time), _replay_time(knowledge_time)
        eligible = [item for item in self.list(workspace_id) if item.published_at <= knowledge_time]
        if not eligible:
            raise GraphSnapshotNotFoundError((workspace_id, knowledge_time))
        source = eligible[-1]
        visible = source.visible_edge_states(as_of_time=as_of_time, knowledge_time=knowledge_time)
        replay_id = f"{source.snapshot_id}@{as_of_time.isoformat()}#{knowledge_time.isoformat()}"
        return source.model_copy(
            update={
                "snapshot_id": replay_id,
                "as_of_time": as_of_time,
                "knowledge_time": knowledge_time,
                "edge_states": visible,
            }
        )


class PostgresTemporalGraphRepository:
    """PostgreSQL snapshot storage, accepting a small DB-API connection surface."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def publish(self, snapshot: TemporalGraphSnapshot) -> GraphPublicationReceipt:
        digest, payload = snapshot.content_sha256(), canonical_json(snapshot)
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                "SELECT content_sha256 FROM temporal_graph_snapshots WHERE snapshot_id = %s",
                (snapshot.snapshot_id,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if str(existing[0]) != digest:
                    raise ImmutableGraphSnapshotError(
                        f"snapshot {snapshot.snapshot_id!r} is immutable"
                    )
                return _receipt(snapshot)
            cursor.execute(
                "INSERT INTO temporal_graph_snapshots "
                "(snapshot_id, workspace_id, universe_id, parent_snapshot_id, "
                "published_at, as_of_time, "
                "knowledge_time, content_sha256, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (
                    snapshot.snapshot_id,
                    snapshot.workspace_id,
                    snapshot.universe_id,
                    snapshot.parent_snapshot_id,
                    snapshot.published_at,
                    snapshot.as_of_time,
                    snapshot.knowledge_time,
                    digest,
                    payload,
                ),
            )
            self._connection.commit()
        except Exception:
            rollback = getattr(self._connection, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        return _receipt(snapshot)

    def get(self, snapshot_id: str) -> TemporalGraphSnapshot:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM temporal_graph_snapshots WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise GraphSnapshotNotFoundError(snapshot_id)
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return TypeAdapter(TemporalGraphSnapshot).validate_python(payload)

    def list(self, workspace_id: str) -> list[TemporalGraphSnapshot]:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM temporal_graph_snapshots "
            "WHERE workspace_id = %s ORDER BY published_at, snapshot_id",
            (workspace_id,),
        )
        snapshots = []
        for row in cursor.fetchall():
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            snapshots.append(TypeAdapter(TemporalGraphSnapshot).validate_python(payload))
        return snapshots

    def latest(self, workspace_id: str) -> TemporalGraphSnapshot:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM temporal_graph_snapshots WHERE workspace_id = %s "
            "ORDER BY published_at DESC, snapshot_id DESC LIMIT 1",
            (workspace_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise GraphSnapshotNotFoundError(workspace_id)
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return TypeAdapter(TemporalGraphSnapshot).validate_python(payload)

    def replay(
        self, workspace_id: str, *, as_of_time: datetime, knowledge_time: datetime
    ) -> TemporalGraphSnapshot:
        as_of_time, knowledge_time = _replay_time(as_of_time), _replay_time(knowledge_time)
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM temporal_graph_snapshots WHERE workspace_id = %s "
            "AND published_at <= %s ORDER BY published_at DESC, snapshot_id DESC LIMIT 1",
            (workspace_id, knowledge_time),
        )
        row = cursor.fetchone()
        if row is None:
            raise GraphSnapshotNotFoundError((workspace_id, knowledge_time))
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        source = TypeAdapter(TemporalGraphSnapshot).validate_python(payload)
        edges = source.visible_edge_states(as_of_time=as_of_time, knowledge_time=knowledge_time)
        replay_id = f"{source.snapshot_id}@{as_of_time.isoformat()}#{knowledge_time.isoformat()}"
        return source.model_copy(
            update={
                "snapshot_id": replay_id,
                "as_of_time": as_of_time,
                "knowledge_time": knowledge_time,
                "edge_states": edges,
            }
        )
