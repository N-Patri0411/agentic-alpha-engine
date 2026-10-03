from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from alpha_workbench.evidence import (
    DuckDBEvidenceLedger,
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.graph_pipeline import (
    DuckDBGraphInputProvider,
    GraphInputs,
    graph_refresh_handler,
)
from alpha_workbench.jobs import JobWorker
from alpha_workbench.product import DomainWorkspace, InstrumentRef, UniverseSpec
from alpha_workbench.server.app import create_app, make_in_memory_dependencies
from alpha_workbench.temporal_graph import (
    GraphEdgeState,
    GraphNode,
    GraphRelationship,
    TemporalGraphSnapshot,
)

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


class EmptyInputs:
    def load(self, universe, *, as_of_time, knowledge_time):
        return GraphInputs(warnings=("Fixture has no relevant evidence.",))


def _ten_instrument_universe() -> UniverseSpec:
    return UniverseSpec(
        universe_id="u-graph",
        workspace_id="w-graph",
        domain="semiconductors",
        instruments=tuple(
            InstrumentRef(
                instrument_id=f"FIGI:{index}",
                symbol=f"C{index}",
                exchange="XNAS",
                currency="USD",
                entity_id=f"issuer-{index}",
            )
            for index in range(10)
        ),
        selection_time=NOW,
        selection_mode="current",
        selection_method="fixture",
        target_count=10,
    )


def _dependencies(input_provider=None):
    dependencies = make_in_memory_dependencies(
        graph_input_provider=input_provider or EmptyInputs()  # type: ignore[arg-type]
    )
    universe = _ten_instrument_universe()
    dependencies.workspace_repository.put_universe(universe)  # type: ignore[attr-defined]
    dependencies.workspace_repository.put(
        DomainWorkspace(
            workspace_id=universe.workspace_id,
            name="Semiconductor universe",
            domain=universe.domain,
            universe_id=universe.universe_id,
        )
    )
    return dependencies, universe


def _snapshot(universe: UniverseSpec, snapshot_id: str, published_at: datetime):
    nodes = (
        tuple(
            GraphNode(
                node_id=f"entity:issuer-{index}",
                kind="entity",
                label=f"Issuer {index}",
                properties={"instrument_ids": f"FIGI:{index}"},
            )
            for index in range(10)
        )
        + tuple(
            GraphNode(
                node_id=f"FIGI:{index}",
                kind="instrument",
                label=f"C{index}",
                properties={"entity_id": f"entity:issuer-{index}"},
            )
            for index in range(10)
        )
        + (GraphNode(node_id="external:regulator", kind="external_context", label="Regulator"),)
    )
    relationship = GraphRelationship(
        relationship_id="rel-supply", name="manufacturing_dependency", semantics="directed"
    )
    edges = (
        GraphEdgeState(
            edge_id="e1",
            relationship_id=relationship.relationship_id,
            source_node_id="entity:issuer-0",
            target_node_id="entity:issuer-1",
            effective_from=NOW,
            knowledge_from=published_at,
            evidence_ids=("ev-1",),
            confidence=0.9,
            economic_exposure=0.8,
            propagation_coefficient=0.7,
            strategy_eligible="eligible",
            attributes={"last_supported_at": NOW.isoformat()},
        ),
        GraphEdgeState(
            edge_id="e2",
            relationship_id=relationship.relationship_id,
            source_node_id="external:regulator",
            target_node_id="entity:issuer-1",
            effective_from=NOW,
            knowledge_from=published_at,
            evidence_ids=("ev-2",),
            confidence=0.8,
            economic_exposure=0.3,
            propagation_coefficient=0.4,
            attributes={"last_supported_at": NOW.isoformat()},
        ),
    )
    return TemporalGraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id=universe.workspace_id,
        universe_id=universe.universe_id,
        universe_instrument_ids=tuple(item.instrument_id for item in universe.instruments),
        published_at=published_at,
        as_of_time=NOW,
        knowledge_time=published_at,
        nodes=nodes,
        relationships=(relationship,),
        edge_states=edges,
    )


def test_graph_rest_projects_entities_to_instruments_and_reports_real_coverage() -> None:
    dependencies, universe = _dependencies()
    first = _snapshot(universe, "snap-1", NOW)
    dependencies.graph_repository.publish(first)
    client = TestClient(create_app(dependencies))

    response = client.get("/api/graph-snapshots/snap-1")
    assert response.status_code == 200
    wire = response.json()
    assert len([node for node in wire["nodes"] if node["tradeable"]]) == 10
    assert not any(node["node_kind"] == "entity" for node in wire["nodes"])
    assert any(node["node_kind"] == "external_context" for node in wire["nodes"])
    projected = {(item["source_node_id"], item["target_node_id"]) for item in wire["relationships"]}
    assert ("FIGI:0", "FIGI:1") in projected
    assert ("external:regulator", "FIGI:1") in projected
    assert wire["coverage"] == {
        "tradeable_connected": 2,
        "total_tradeable": 10,
        "eligible_relationships": 1,
        "total_relationships": 2,
        "freshness": 1.0,
    }
    assert (
        client.get("/api/workspaces/w-graph/graph/snapshots").json()[0]["eligible_relationships"]
        == 1
    )

    next_snapshot = _snapshot(universe, "snap-2", NOW + timedelta(minutes=1)).model_copy(
        update={
            "edge_states": first.edge_states
            + (
                first.edge_states[0].model_copy(
                    update={"edge_id": "e3", "target_node_id": "entity:issuer-2"}
                ),
            )
        }
    )
    dependencies.graph_repository.publish(next_snapshot)
    diff = client.get("/api/graph-snapshots/snap-2/diff", params={"compare_to": "snap-1"})
    assert diff.status_code == 200
    assert any(row["kind"] == "relationship" for row in diff.json()["added"])


def test_graph_refresh_job_is_durable_idempotent_and_empty_evidence_is_node_only() -> None:
    dependencies, _ = _dependencies()
    client = TestClient(create_app(dependencies))
    path = "/api/workspaces/w-graph/graph-refresh"
    first = client.post(path, json={"idempotency_key": "refresh-1"})
    replay = client.post(path, json={"idempotency_key": "refresh-1"})
    assert first.status_code == 202
    assert first.json()["id"] == replay.json()["id"]
    job_id = first.json()["id"]
    receipt = dependencies.job_repository.get(job_id)
    assert receipt is not None and receipt.status.value == "queued"

    # A newly constructed worker resumes the durable queued payload after restart.
    worker = JobWorker(
        dependencies.dispatcher,
        {
            "graph-refresh": graph_refresh_handler(
                dependencies.workspace_repository,
                dependencies.graph_repository,
                dependencies.graph_input_provider,
            )
        },
    )
    assert worker.run_once()
    completed = client.get(f"/api/jobs/{job_id}").json()
    assert completed["status"] == "succeeded"
    snapshot = dependencies.graph_repository.latest("w-graph")
    assert len(snapshot.universe_instrument_ids) == 10
    assert snapshot.edge_states == ()
    events = client.get(f"/api/jobs/{job_id}/events").json()
    assert any("node-only" in str(event.get("message")) for event in events)
    assert (
        client.get(f"/api/graph-snapshots/{snapshot.snapshot_id}").json()["coverage"]["freshness"]
        == 0
    )


def _observation(
    available_at: datetime, *, retrieved_at: datetime | None = None
) -> EvidenceObservation:
    text = "Company issuer-0 relies on issuer-1 for a critical chip supply agreement."
    return EvidenceObservation(
        idempotency_key=f"future:{available_at.isoformat()}",
        document=SourceDocument(
            source_kind="sec_filing",
            source_tier="primary",
            source_adapter="fixture",
            source_url="https://example.test/filing",
            content_sha256="a" * 64,
            issuer_entity_id="issuer-0",
            observed_at=available_at,
            available_at=available_at,
            retrieved_at=retrieved_at or available_at,
            usage_note="synthetic future-leakage fixture",
        ),
        mentioned_entity_ids=("issuer-0", "issuer-1"),
        payload=TextEvidence(
            text=text, exact_quote=text, character_start=0, character_end=len(text)
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="future-run"
        ),
    )


def test_duckdb_graph_provider_excludes_future_evidence(tmp_path: Path) -> None:
    path = tmp_path / "evidence.duckdb"
    with DuckDBEvidenceLedger(path) as ledger:
        ledger.append(_observation(NOW + timedelta(days=1)))
    provider = DuckDBGraphInputProvider(path)
    inputs = provider.load(
        _ten_instrument_universe(),
        as_of_time=NOW,
        knowledge_time=NOW,
    )
    assert inputs.observations == ()
    assert "No evidence" in inputs.warnings[0]


def test_duckdb_graph_provider_excludes_evidence_retrieved_after_knowledge_cutoff(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.duckdb"
    with DuckDBEvidenceLedger(path) as ledger:
        ledger.append(_observation(NOW, retrieved_at=NOW + timedelta(days=1)))
    inputs = DuckDBGraphInputProvider(path).load(
        _ten_instrument_universe(),
        as_of_time=NOW,
        knowledge_time=NOW,
    )
    assert inputs.observations == ()
    assert "No evidence" in inputs.warnings[0]


def test_configured_extraction_failure_is_recorded_without_secret_values() -> None:
    class FailingInputs:
        def load(self, universe, *, as_of_time, knowledge_time):
            raise RuntimeError("missing required local environment variable OPENAI_API_KEY")

    dependencies, _ = _dependencies(FailingInputs())
    client = TestClient(create_app(dependencies))
    submitted = client.post("/api/workspaces/w-graph/graph-refresh", json={})
    job_id = submitted.json()["id"]
    worker = JobWorker(
        dependencies.dispatcher,
        {
            "graph-refresh": graph_refresh_handler(
                dependencies.workspace_repository,
                dependencies.graph_repository,
                dependencies.graph_input_provider,
            )
        },
    )
    worker.run_once()
    receipt = client.get(f"/api/jobs/{job_id}").json()
    assert receipt["status"] == "failed"
    assert "OPENAI_API_KEY" in receipt["message"]
    assert "sk-secret" not in receipt["message"]
