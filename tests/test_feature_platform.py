from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from alpha_workbench.features import (
    FeatureInputFrame,
    FeatureInputObservation,
    FeatureSetVersion,
    ImmutableFeatureRecordError,
    InMemoryFeatureRepository,
    PostgresFeatureRepository,
    build_feature_frame,
    default_feature_catalog,
    feature_catalog,
)
from alpha_workbench.temporal_graph import (
    GraphEdgeState,
    GraphNode,
    GraphRelationship,
    TemporalGraphSnapshot,
)

AS_OF = datetime(2026, 10, 1, 21, tzinfo=UTC)


def _snapshot(snapshot_id: str = "graph-v1", *, second_edge: bool = False):
    relationship = GraphRelationship(relationship_id="dep", name="dependency", semantics="directed")
    nodes = (
        GraphNode(node_id="entity:A", kind="entity", label="A"),
        GraphNode(node_id="entity:B", kind="entity", label="B"),
        GraphNode(
            node_id="instrument:A",
            kind="instrument",
            label="A",
            properties={"entity_id": "entity:A"},
        ),
        GraphNode(
            node_id="instrument:B",
            kind="instrument",
            label="B",
            properties={"entity_id": "entity:B"},
        ),
    )
    edges = [
        GraphEdgeState(
            edge_id="edge-1",
            relationship_id="dep",
            source_node_id="entity:A",
            target_node_id="entity:B",
            effective_from=AS_OF - timedelta(days=10),
            knowledge_from=AS_OF - timedelta(days=10),
            evidence_ids=("ev-1",),
            confidence=0.8,
            economic_exposure=0.5,
            propagation_coefficient=0.4,
            strategy_eligible="eligible",
        )
    ]
    if second_edge:
        edges.append(
            GraphEdgeState(
                edge_id="edge-2",
                relationship_id="dep",
                source_node_id="entity:B",
                target_node_id="entity:A",
                effective_from=AS_OF - timedelta(days=2),
                knowledge_from=AS_OF - timedelta(days=2),
                evidence_ids=("ev-2",),
                confidence=0.7,
                economic_exposure=0.3,
                propagation_coefficient=0.2,
                strategy_eligible="eligible",
            )
        )
    return TemporalGraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id="w",
        universe_id="u",
        universe_instrument_ids=("instrument:A", "instrument:B"),
        published_at=AS_OF - timedelta(days=1),
        as_of_time=AS_OF,
        knowledge_time=AS_OF,
        nodes=nodes,
        relationships=(relationship,),
        edge_states=tuple(edges),
    )


def _frame(family, frequency, values, *, version="dataset-v1"):
    rows = tuple(
        FeatureInputObservation(
            entity_id=entity,
            observed_at=AS_OF - timedelta(days=days),
            available_at=AS_OF - timedelta(days=days),
            values=row_values,
        )
        for entity, days, row_values in values
    )
    return FeatureInputFrame(
        family=family, frequency=frequency, dataset_version=version, observations=rows
    )


def _fixture_frames():
    frames = {
        "neighbor_lag": _frame("neighbor_lag", "daily", [("entity:A", 1, {"signal": 0.6})]),
        "statistical_lead_lag": _frame(
            "statistical_lead_lag",
            "daily",
            [
                ("basket", 3, {"x": 1, "y": 2}),
                ("basket", 2, {"x": 2, "y": 4}),
                ("basket", 1, {"x": 3, "y": 6}),
            ],
        ),
        "price_volume": _frame(
            "price_volume",
            "daily",
            [("A", 2, {"close": 100, "volume": 10}), ("A", 1, {"close": 110, "volume": 20})],
        ),
        "volatility": _frame(
            "volatility",
            "daily",
            [("A", 3, {"close": 100}), ("A", 2, {"close": 110}), ("A", 1, {"close": 121})],
        ),
        "fundamentals": _frame(
            "fundamentals",
            "quarterly",
            [("A", 1, {"revenue": 100, "gross_profit": 40, "net_income": 10, "total_assets": 200})],
        ),
        "earnings_events": _frame(
            "earnings_events",
            "event",
            [("A", 2, {"actual": 1.2, "consensus": 1}), ("A", 1, {"actual": 1.1, "consensus": 1})],
        ),
        "language_drift": _frame(
            "language_drift",
            "daily",
            [("A", 2, {"sentiment": -0.1}), ("A", 1, {"sentiment": 0.3})],
        ),
        "macro_fx": _frame(
            "macro_fx",
            "daily",
            [
                ("USD", 2, {"macro": 100, "fx_rate": 1.0}),
                ("USD", 1, {"macro": 102, "fx_rate": 1.1}),
            ],
        ),
    }
    return frames


def _feature_set(catalog, frames, graph):
    return FeatureSetVersion(
        feature_set_id="all-features",
        feature_definition_refs=tuple(f"{item.feature_id}:v{item.version}" for item in catalog),
        dataset_versions={family: frame.dataset_version for family, frame in frames.items()},
        graph_snapshot_id=graph.snapshot_id,
        graph_snapshot_digest=graph.content_digest,
    )


def test_deterministic_builders_compute_every_advertised_family() -> None:
    catalog = default_feature_catalog()
    frames = _fixture_frames()
    graph = _snapshot()
    feature_set = _feature_set(catalog, frames, graph)
    manifest = build_feature_frame(
        feature_set,
        catalog,
        input_frames=frames,
        as_of_time=AS_OF,
        graph_snapshot=graph,
    )
    repeated = build_feature_frame(
        feature_set,
        catalog,
        input_frames=frames,
        as_of_time=AS_OF,
        graph_snapshot=graph,
    )
    assert manifest.content_sha256() == repeated.content_sha256()
    assert manifest.feature_set_digest == feature_set.content_sha256()
    assert set(manifest.feature_definition_digests) == {
        f"{item.feature_id}:v{item.version}" for item in catalog
    }
    assert {entry.readiness.status for entry in feature_catalog(catalog, manifest)} == {"ready"}
    values = {
        (item.feature_name, item.entity_id): item.value for item in manifest.feature_observations
    }
    assert values[("graph_propagation_exposure", "entity:B")] == pytest.approx(0.2)
    assert values[("neighbor_signal_lag", "entity:B")] == pytest.approx(0.6)
    assert values[("graph_degree_centrality", "entity:A")] > 0
    assert values[("graph_exposure_concentration", "entity:A")] == pytest.approx(1.0)
    assert values[("lead_lag_correlation", "basket")] == pytest.approx(1.0)
    assert values[("close_return", "A")] == pytest.approx(0.1)
    assert values[("volume_change", "A")] == pytest.approx(1.0)
    assert values[("realized_volatility", "A")] == pytest.approx(0.0)
    assert values[("gross_margin", "A")] == pytest.approx(0.4)
    assert values[("return_on_assets", "A")] == pytest.approx(0.05)
    assert values[("earnings_surprise", "A")] == pytest.approx(0.1)
    assert values[("event_count_30d", "A")] == 2
    assert isinstance(values[("event_count_30d", "A")], int)
    assert values[("language_sentiment_drift", "A")] == pytest.approx(0.4)
    assert values[("macro_change", "USD")] == pytest.approx(0.02)
    assert values[("fx_return", "USD")] == pytest.approx(0.1)


def test_missing_source_family_is_explicitly_unavailable() -> None:
    catalog = default_feature_catalog()
    graph = _snapshot()
    feature_set = _feature_set(catalog, {}, graph)
    manifest = build_feature_frame(
        feature_set, catalog, input_frames={}, as_of_time=AS_OF, graph_snapshot=graph
    )
    assert (
        next(item for item in manifest.readiness if item.feature_id == "close_return").status
        == "unavailable"
    )
    assert (
        "no source frame"
        in next(item for item in manifest.readiness if item.feature_id == "close_return").reason
    )


def test_builder_rejects_future_input_frequency_and_dataset_mismatch() -> None:
    catalog = default_feature_catalog()
    definition = next(item for item in catalog if item.name == "close_return")
    feature_set = FeatureSetVersion(
        feature_set_id="prices",
        feature_definition_refs=("close_return:v1",),
        dataset_versions={"price_volume": "dataset-v1"},
    )
    future = FeatureInputFrame(
        family="price_volume",
        frequency="daily",
        dataset_version="dataset-v1",
        observations=(
            FeatureInputObservation(
                entity_id="A",
                observed_at=AS_OF + timedelta(seconds=1),
                available_at=AS_OF + timedelta(seconds=1),
                values={"close": 10},
            ),
        ),
    )
    with pytest.raises(ValueError, match="after as_of_time"):
        build_feature_frame(
            feature_set, (definition,), input_frames={"price_volume": future}, as_of_time=AS_OF
        )
    wrong_freq = _frame("price_volume", "weekly", [("A", 1, {"close": 10})])
    with pytest.raises(ValueError, match="requires daily"):
        build_feature_frame(
            feature_set, (definition,), input_frames={"price_volume": wrong_freq}, as_of_time=AS_OF
        )
    wrong_version = _frame("price_volume", "daily", [("A", 1, {"close": 10})], version="dataset-v2")
    with pytest.raises(ValueError, match="not pinned"):
        build_feature_frame(
            feature_set,
            (definition,),
            input_frames={"price_volume": wrong_version},
            as_of_time=AS_OF,
        )


def test_builder_rejects_definition_schema_without_matching_implementation() -> None:
    definition = next(item for item in default_feature_catalog() if item.name == "close_return")
    altered = definition.model_copy(update={"inputs": ("volume",)})
    feature_set = FeatureSetVersion(
        feature_set_id="prices",
        feature_definition_refs=("close_return:v1",),
        dataset_versions={"price_volume": "dataset-v1"},
    )
    with pytest.raises(ValueError, match="definition schema"):
        build_feature_frame(
            feature_set,
            (altered,),
            input_frames={},
            as_of_time=AS_OF,
        )


def test_graph_feature_pins_static_and_evolving_graph_versions() -> None:
    catalog = tuple(
        item for item in default_feature_catalog() if item.family == "graph_propagation"
    )
    graph_v1, graph_v2 = _snapshot("g1"), _snapshot("g2", second_edge=True)
    frames = {}
    set_v1 = _feature_set(catalog, frames, graph_v1)
    set_v2 = FeatureSetVersion(
        feature_set_id="static-graph",
        version=2,
        feature_definition_refs=set_v1.feature_definition_refs,
        graph_snapshot_id=graph_v2.snapshot_id,
        graph_snapshot_digest=graph_v2.content_digest,
    )
    output_v1 = build_feature_frame(
        set_v1, catalog, input_frames=frames, as_of_time=AS_OF, graph_snapshot=graph_v1
    )
    output_v2 = build_feature_frame(
        set_v2, catalog, input_frames=frames, as_of_time=AS_OF, graph_snapshot=graph_v2
    )
    assert output_v1.graph_snapshot_id == "g1"
    assert output_v2.graph_snapshot_id == "g2"
    assert output_v1.feature_observations != output_v2.feature_observations
    with pytest.raises(ValueError, match="does not match"):
        build_feature_frame(
            set_v1, catalog, input_frames=frames, as_of_time=AS_OF, graph_snapshot=graph_v2
        )


def test_feature_records_and_manifests_are_immutable_and_round_trip_in_memory() -> None:
    repo = InMemoryFeatureRepository()
    definition = default_feature_catalog()[0]
    stored = repo.put_definition(definition)
    assert repo.get_definition(definition.feature_id) == stored
    with pytest.raises(ImmutableFeatureRecordError):
        repo.put_definition(definition.model_copy(update={"description": "changed"}))
    graph = _snapshot()
    feature_set = _feature_set((definition,), {}, graph)
    repo.put_feature_set(feature_set)
    manifest = build_feature_frame(
        feature_set, (definition,), input_frames={}, as_of_time=AS_OF, graph_snapshot=graph
    )
    repo.put_manifest(manifest)
    assert repo.get_manifest(manifest.manifest_id) == manifest
    observation = manifest.feature_observations[0]
    repo.put_observation(observation)
    assert repo.get_observation(observation.observation_id) == observation
    with pytest.raises(ImmutableFeatureRecordError):
        repo.put_manifest(manifest.model_copy(update={"as_of_time": AS_OF + timedelta(days=1)}))


def test_contracts_reject_naive_clocks_and_incomplete_graph_pins() -> None:
    with pytest.raises(ValidationError):
        FeatureInputObservation(
            entity_id="A",
            observed_at=datetime(2026, 1, 1),
            available_at=datetime(2026, 1, 2),
            values={},
        )
    with pytest.raises(ValidationError, match="must be pinned together"):
        FeatureSetVersion(
            feature_set_id="bad", feature_definition_refs=("x:v1",), graph_snapshot_id="g1"
        )


class _RecordingCursor:
    def __init__(self, existing=None):
        self.statements = []
        self.existing = existing

    def execute(self, query, parameters):
        self.statements.append((query, parameters))

    def fetchone(self):
        return self.existing

    def fetchall(self):
        return []


class _RecordingConnection:
    def __init__(self, existing=None):
        self.recording_cursor = _RecordingCursor(existing)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.recording_cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_postgres_repository_insert_is_parameterized_and_migration_is_append_only():
    definition = default_feature_catalog()[0]
    connection = _RecordingConnection()
    assert PostgresFeatureRepository(connection).put_definition(definition) == definition
    assert connection.commits == 1
    query, parameters = connection.recording_cursor.statements[1]
    assert "INSERT INTO feature_artifacts" in query
    assert parameters[0:3] == ("definition", definition.feature_id, definition.version)
    migration = (Path(__file__).parents[1] / "infra" / "migrations" / "004_features.sql").read_text(
        encoding="utf-8"
    )
    assert "PRIMARY KEY (artifact_kind, artifact_id, version)" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "DROP TABLE" not in migration
