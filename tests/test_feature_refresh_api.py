from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from alpha_workbench.jobs.__main__ import worker_handlers
from alpha_workbench.product import DomainWorkspace, InstrumentRef, UniverseSpec
from alpha_workbench.server.app import create_app, make_in_memory_dependencies
from alpha_workbench.temporal_graph import (
    GraphEdgeState,
    GraphNode,
    GraphRelationship,
    TemporalGraphSnapshot,
)

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
WORKSPACE_ID = "w-feature-refresh"
UNIVERSE_ID = "u-feature-refresh"


def _universe(workspace_id: str = WORKSPACE_ID, universe_id: str = UNIVERSE_ID) -> UniverseSpec:
    return UniverseSpec(
        universe_id=universe_id,
        workspace_id=workspace_id,
        domain="semiconductors",
        instruments=(
            InstrumentRef(
                instrument_id="FIGI:A",
                symbol="AAA",
                exchange="XNAS",
                currency="USD",
                entity_id="issuer-a",
            ),
            InstrumentRef(
                instrument_id="FIGI:B",
                symbol="BBB",
                exchange="XNAS",
                currency="USD",
                entity_id="issuer-b",
            ),
        ),
        selection_time=NOW,
        selection_mode="current",
        selection_method="fixture",
        target_count=2,
    )


def _snapshot(
    universe: UniverseSpec,
    snapshot_id: str,
    *,
    published_at: datetime,
    as_of_time: datetime = NOW,
) -> TemporalGraphSnapshot:
    relation = GraphRelationship(
        relationship_id="supply", name="supply_dependency", semantics="directed"
    )
    return TemporalGraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id=universe.workspace_id,
        universe_id=universe.universe_id,
        universe_instrument_ids=tuple(item.instrument_id for item in universe.instruments),
        published_at=published_at,
        as_of_time=as_of_time,
        knowledge_time=NOW,
        nodes=(
            GraphNode(node_id="FIGI:A", kind="instrument", label="AAA"),
            GraphNode(node_id="FIGI:B", kind="instrument", label="BBB"),
        ),
        relationships=(relation,),
        edge_states=(
            GraphEdgeState(
                edge_id=f"edge-{snapshot_id}",
                relationship_id=relation.relationship_id,
                source_node_id="FIGI:A",
                target_node_id="FIGI:B",
                effective_from=as_of_time - timedelta(days=1),
                knowledge_from=min(published_at, NOW),
                evidence_ids=(f"evidence-{snapshot_id}",),
                confidence=0.9,
                economic_exposure=0.8,
                propagation_coefficient=0.5,
                strategy_eligible="eligible",
            ),
        ),
    )


def _setup(snapshot_id: str = "graph-a", *, published_at: datetime = NOW):
    dependencies = make_in_memory_dependencies()
    universe = _universe()
    dependencies.workspace_repository.put_universe(universe)
    graph = _snapshot(universe, snapshot_id, published_at=published_at)
    dependencies.graph_repository.publish(graph)
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=WORKSPACE_ID,
            name="Feature refresh fixture",
            domain="semiconductors",
            universe_id=UNIVERSE_ID,
            graph_version_id=snapshot_id,
        )
    )
    return dependencies, universe, TestClient(create_app(dependencies))


def _refresh(client: TestClient, key: str = "run-1"):
    return client.post(
        f"/api/workspaces/{WORKSPACE_ID}/feature-refresh",
        json={"idempotency_key": key},
    )


def test_feature_refresh_persists_graph_features_and_enables_alpha_candidates() -> None:
    dependencies, _, client = _setup()
    response = _refresh(client)
    assert response.status_code == 202
    assert response.json()["kind"] == "feature-refresh"
    assert dependencies.worker is not None
    dependencies.worker.run_once()

    features = client.get(f"/api/workspaces/{WORKSPACE_ID}/features").json()["features"]
    ready = {item["feature_id"] for item in features if item["available"]}
    assert "graph_propagation_exposure" in ready
    assert "graph_degree_centrality" in ready
    assert "neighbor_signal_lag" not in ready
    assert "close_return" not in ready

    candidates = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates",
        json={
            "intent": "Explore instrument exposure",
            "feature_names": ["graph_propagation_exposure"],
            "universe_id": UNIVERSE_ID,
            "graph_snapshot_id": "graph-a",
        },
    )
    assert candidates.status_code == 200


def test_identical_refresh_replay_does_not_duplicate_artifacts_or_bindings() -> None:
    dependencies, _, client = _setup()
    first = _refresh(client)
    dependencies.worker.run_once()  # type: ignore[union-attr]
    second = _refresh(client)
    assert second.json()["id"] == first.json()["id"]
    assert len(dependencies.feature_repository._records) > 0  # type: ignore[attr-defined]
    before = len(dependencies.feature_bindings.list_bindings(WORKSPACE_ID))

    # A different key repeats the deterministic refresh and exercises artifact-level idempotency.
    third = _refresh(client, "run-2")
    dependencies.worker.run_once()  # type: ignore[union-attr]
    assert third.status_code == 202
    assert len(dependencies.feature_bindings.list_bindings(WORKSPACE_ID)) == before


def test_changed_graph_snapshot_appends_a_new_binding_version() -> None:
    dependencies, universe, client = _setup()
    _refresh(client, "first")
    dependencies.worker.run_once()  # type: ignore[union-attr]
    prior = next(
        item
        for item in dependencies.feature_bindings.list_bindings(WORKSPACE_ID)
        if item.feature_id == "graph_propagation_exposure"
    )

    graph = _snapshot(universe, "graph-b", published_at=NOW)
    dependencies.graph_repository.publish(graph)
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=WORKSPACE_ID,
            version=2,
            name="Feature refresh fixture",
            domain="semiconductors",
            universe_id=UNIVERSE_ID,
            graph_version_id="graph-b",
        )
    )
    _refresh(client, "second")
    dependencies.worker.run_once()  # type: ignore[union-attr]
    versions = [
        item.version
        for item in dependencies.feature_bindings.list_bindings(WORKSPACE_ID)
        if item.feature_id == "graph_propagation_exposure"
    ]
    assert versions == [prior.version, prior.version + 1]


def test_refresh_rejects_graph_ownership_mismatch_and_future_publication() -> None:
    dependencies, _, client = _setup()
    foreign_universe = _universe("other-workspace", "other-universe")
    dependencies.workspace_repository.put_universe(foreign_universe)
    mismatched = _snapshot(
        foreign_universe,
        "foreign-graph",
        published_at=NOW - timedelta(minutes=1),
    )
    dependencies.graph_repository.publish(mismatched)
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=WORKSPACE_ID,
            version=2,
            name="Feature refresh fixture",
            domain="semiconductors",
            universe_id=UNIVERSE_ID,
            graph_version_id="foreign-graph",
        )
    )
    assert _refresh(client, "mismatch").status_code == 409

    future = _snapshot(
        _universe(), "future-graph", published_at=datetime.now(UTC) + timedelta(days=1)
    )
    dependencies.graph_repository.publish(future)
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=WORKSPACE_ID,
            version=3,
            name="Feature refresh fixture",
            domain="semiconductors",
            universe_id=UNIVERSE_ID,
            graph_version_id="future-graph",
        )
    )
    assert _refresh(client, "future").status_code == 409


def test_published_after_effective_time_never_makes_features_available_early() -> None:
    effective_time = NOW - timedelta(days=1)
    dependencies, universe, client = _setup(published_at=NOW)
    graph = _snapshot(
        universe,
        "graph-delayed-publication",
        published_at=NOW,
        as_of_time=effective_time,
    )
    dependencies.graph_repository.publish(graph)
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=WORKSPACE_ID,
            version=2,
            name="Feature refresh fixture",
            domain="semiconductors",
            universe_id=UNIVERSE_ID,
            graph_version_id=graph.snapshot_id,
        )
    )

    assert _refresh(client, "delayed-publication").status_code == 202
    dependencies.worker.run_once()  # type: ignore[union-attr]
    binding = next(
        item
        for item in dependencies.feature_bindings.list_bindings(WORKSPACE_ID)
        if item.feature_id == "graph_propagation_exposure"
    )
    manifest = next(
        record
        for (record_type, _, _), record in dependencies.feature_repository._records.items()  # type: ignore[attr-defined]
        if record_type.__name__ == "FeatureFrameManifest"
        and record.manifest_id == binding.source_artifact_ids[0]
    )
    observation = next(
        item
        for item in manifest.feature_observations
        if item.feature_id == "graph_propagation_exposure"
    )
    assert manifest.as_of_time == NOW
    assert manifest.effective_time == effective_time
    assert manifest.knowledge_time == NOW
    assert observation.observed_at == effective_time
    assert observation.available_at == NOW
    assert binding.available_at == NOW
    candidates = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates",
        json={
            "intent": "Explore instrument exposure",
            "feature_names": ["graph_propagation_exposure"],
            "universe_id": UNIVERSE_ID,
            "graph_snapshot_id": graph.snapshot_id,
        },
    )
    assert candidates.status_code == 200


def test_standalone_worker_registers_feature_refresh() -> None:
    dependencies, _, _ = _setup()
    handlers = worker_handlers(
        dependencies.workspace_repository,
        dependencies.graph_repository,
        dependencies.graph_input_provider,
        dependencies.feature_repository,
        dependencies.feature_bindings,
    )
    assert "feature-refresh" in handlers
