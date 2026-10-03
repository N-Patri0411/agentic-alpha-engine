from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from alpha_workbench.temporal_graph import (
    BoundedGraphAnalysis,
    GraphEdgeState,
    GraphNode,
    GraphRelationship,
    ImmutableGraphSnapshotError,
    InMemoryTemporalGraphRepository,
    PostgresTemporalGraphRepository,
    TemporalGraphSnapshot,
    diff_snapshots,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def make_snapshot(
    snapshot_id: str = "s1",
    *,
    published_at: datetime = T0,
    relationship: GraphRelationship | None = None,
    edge_states: tuple[GraphEdgeState, ...] | None = None,
) -> TemporalGraphSnapshot:
    nodes = tuple(
        GraphNode(node_id=f"FIGI:{index}", kind="instrument", label=f"I{index}")
        for index in range(10)
    ) + (GraphNode(node_id="REG:US", kind="external_context", label="US regulator"),)
    rel = relationship or GraphRelationship(
        relationship_id="supplies", name="supplies", semantics="directed"
    )
    edges = (
        edge_states
        if edge_states is not None
        else (
            GraphEdgeState(
                edge_id="e1",
                relationship_id=rel.relationship_id,
                source_node_id="FIGI:0",
                target_node_id="FIGI:1",
                effective_from=T0,
                knowledge_from=T0,
                evidence_ids=("evidence-1",),
                confidence=0.9,
                economic_exposure=1.5,
                propagation_coefficient=0.7,
                strategy_eligible="eligible",
            ),
        )
    )
    return TemporalGraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id="w1",
        universe_id="u1",
        universe_instrument_ids=tuple(f"FIGI:{index}" for index in range(10)),
        published_at=published_at,
        as_of_time=T0,
        knowledge_time=published_at,
        nodes=nodes,
        relationships=(rel,),
        edge_states=edges,
    )


def test_temporal_snapshot_is_frozen_full_graph_and_accepts_external_context() -> None:
    snapshot = make_snapshot()
    assert len(snapshot.universe_instrument_ids) == 10
    assert snapshot.nodes[-1].kind == "external_context"
    assert snapshot.nodes[0].kind == "instrument"
    with pytest.raises(ValidationError):
        snapshot.workspace_id = "changed"  # type: ignore[misc]


def test_edge_temporal_clocks_and_replay_do_not_rewrite_history() -> None:
    later = T0 + timedelta(days=5)
    future_edge = GraphEdgeState(
        edge_id="later",
        relationship_id="supplies",
        source_node_id="FIGI:1",
        target_node_id="REG:US",
        effective_from=later,
        knowledge_from=later,
        evidence_ids=("new-evidence",),
        confidence=0.8,
        economic_exposure=2,
        propagation_coefficient=0.5,
    )
    first = make_snapshot()
    second = make_snapshot("s2", published_at=later, edge_states=(*first.edge_states, future_edge))
    repo = InMemoryTemporalGraphRepository()
    repo.publish(first)
    repo.publish(second)

    historical = repo.replay("w1", as_of_time=T0, knowledge_time=T0 + timedelta(days=1))
    replayed_later = repo.replay(
        "w1", as_of_time=later + timedelta(days=1), knowledge_time=later + timedelta(days=1)
    )
    assert [edge.edge_id for edge in historical.edge_states] == ["e1"]
    assert {edge.edge_id for edge in replayed_later.edge_states} == {"e1", "later"}
    assert repo.get("s1").content_sha256() == first.content_sha256()
    assert len(repo.list("w1")) == 2
    assert repo.latest("w1").snapshot_id == "s2"


def test_retirement_replay_preserves_active_history_then_exposes_retired_state() -> None:
    learned_at = T0 + timedelta(days=5)
    retirement_at = T0 + timedelta(days=10)
    original = make_snapshot()
    active_before = original.edge_states[0].model_copy(
        update={"effective_to": retirement_at, "knowledge_from": learned_at}
    )
    retired_after = original.edge_states[0].model_copy(
        update={
            "edge_id": "e1-retired",
            "effective_from": retirement_at,
            "knowledge_from": learned_at,
            "lifecycle_status": "retracted",
            "evidence_ids": ("retirement-evidence",),
        }
    )
    updated = make_snapshot(
        "s2", published_at=learned_at, edge_states=(active_before, retired_after)
    )
    repo = InMemoryTemporalGraphRepository()
    repo.publish(original)
    repo.publish(updated)

    before_learning = repo.replay(
        "w1",
        as_of_time=retirement_at - timedelta(days=1),
        knowledge_time=learned_at - timedelta(seconds=1),
    )
    before_retirement = repo.replay(
        "w1", as_of_time=retirement_at - timedelta(seconds=1), knowledge_time=learned_at
    )
    at_retirement = repo.replay("w1", as_of_time=retirement_at, knowledge_time=learned_at)
    assert [edge.lifecycle_status for edge in before_learning.edge_states] == ["active"]
    assert [edge.lifecycle_status for edge in before_retirement.edge_states] == ["active"]
    assert [edge.lifecycle_status for edge in at_retirement.edge_states] == ["retracted"]


def test_snapshot_rejects_reversed_duplicate_symmetric_edge_but_allows_directed_pair() -> None:
    symmetric = GraphRelationship(relationship_id="peers", name="peer", semantics="symmetric")
    edge_one = GraphEdgeState(
        edge_id="a",
        relationship_id="peers",
        source_node_id="FIGI:0",
        target_node_id="FIGI:1",
        effective_from=T0,
        knowledge_from=T0,
        evidence_ids=("ev1",),
        confidence=1,
        economic_exposure=0.2,
        propagation_coefficient=0.4,
    )
    edge_two = edge_one.model_copy(
        update={
            "edge_id": "b",
            "source_node_id": "FIGI:1",
            "target_node_id": "FIGI:0",
            "evidence_ids": ("ev2",),
        }
    )
    with pytest.raises(ValidationError, match="overlapping bitemporal intervals"):
        make_snapshot(relationship=symmetric, edge_states=(edge_one, edge_two))

    directed = symmetric.model_copy(update={"semantics": "directed"})
    snapshot = make_snapshot(relationship=directed, edge_states=(edge_one, edge_two))
    assert len(snapshot.edge_states) == 2

    transition_time = T0 + timedelta(days=3)
    closed_prior = edge_one.model_copy(update={"knowledge_to": transition_time})
    later_state = edge_one.model_copy(
        update={
            "edge_id": "c",
            "knowledge_from": transition_time,
            "knowledge_to": None,
            "evidence_ids": ("ev3",),
            "confidence": 0.7,
        }
    )
    versioned = make_snapshot(relationship=symmetric, edge_states=(closed_prior, later_state))
    assert len(versioned.edge_states) == 2


def test_diff_is_deterministic_and_snapshot_id_cannot_be_reused() -> None:
    prior = make_snapshot()
    changed_edge = prior.edge_states[0].model_copy(update={"confidence": 0.6})
    changed = make_snapshot("s2", published_at=T0 + timedelta(days=1), edge_states=(changed_edge,))
    expected = diff_snapshots(prior, changed)
    assert expected == diff_snapshots(prior, changed)
    assert expected.changed_edge_ids == ("e1",)

    repo = InMemoryTemporalGraphRepository()
    repo.publish(prior)
    with pytest.raises(ImmutableGraphSnapshotError):
        repo.publish(prior.model_copy(update={"as_of_time": T0 + timedelta(days=1)}))


def test_bounded_analysis_respects_directed_and_symmetric_edges() -> None:
    pytest.importorskip("networkx")
    directed = BoundedGraphAnalysis(make_snapshot())
    assert directed.path("FIGI:0", "FIGI:1") == ("FIGI:0", "FIGI:1")
    assert directed.path("FIGI:1", "FIGI:0") is None
    symmetric_relation = GraphRelationship(
        relationship_id="peers", name="peer", semantics="symmetric"
    )
    symmetric_edge = (
        make_snapshot()
        .edge_states[0]
        .model_copy(
            update={
                "relationship_id": "peers",
            }
        )
    )
    symmetric = BoundedGraphAnalysis(
        make_snapshot(relationship=symmetric_relation, edge_states=(symmetric_edge,))
    )
    assert symmetric.path("FIGI:1", "FIGI:0") == ("FIGI:1", "FIGI:0")
    assert len(symmetric.components()) == 10
    assert symmetric.centrality()["FIGI:0"] > 0


class RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> tuple[object] | None:
        return None


class RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_postgres_repository_sql_shape_and_isolated_migration() -> None:
    connection = RecordingConnection()
    repository = PostgresTemporalGraphRepository(connection)
    receipt = repository.publish(make_snapshot())
    assert receipt.snapshot_id == "s1"
    assert connection.commits == 1
    assert (
        "SELECT content_sha256 FROM temporal_graph_snapshots"
        in connection.recording_cursor.statements[0][0]
    )
    insert_sql, values = connection.recording_cursor.statements[1]
    assert "INSERT INTO temporal_graph_snapshots" in insert_sql
    assert "universe_id" in insert_sql and values[2] == "u1"
    assert values[1] == "w1"

    migration_path = Path(__file__).parents[1] / "infra" / "migrations" / "003_temporal_graph.sql"
    sql = migration_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS temporal_graph_snapshots" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "payload->>'universe_id' = universe_id" in sql
    assert "DROP TABLE" not in sql
