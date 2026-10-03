from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from alpha_workbench.agents.alpha_generator import AlphaGeneratorAgent, AlphaGeneratorService
from alpha_workbench.features import WorkspaceFeatureBinding
from alpha_workbench.llm.models import FakeLLMClient
from alpha_workbench.product import DomainWorkspace, InstrumentRef, UniverseSpec
from alpha_workbench.server.app import create_app, make_in_memory_dependencies
from alpha_workbench.temporal_graph import GraphNode, TemporalGraphSnapshot

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
WORKSPACE_ID = "alpha-ws"
UNIVERSE_ID = "alpha-u"
GRAPH_ID = "alpha-g"
FEATURE = "close_return"


def setup_client(response=None, *, workspace_id=WORKSPACE_ID, universe_id=UNIVERSE_ID):
    dependencies = make_in_memory_dependencies()
    instruments = tuple(
        InstrumentRef(instrument_id=f"FIGI:{i}", symbol=f"S{i}", exchange="XNAS", currency="USD")
        for i in range(10)
    )
    universe = UniverseSpec(
        universe_id=universe_id,
        workspace_id=workspace_id,
        domain="semiconductors",
        instruments=instruments,
        selection_time=NOW,
        selection_mode="current",
        selection_method="fixture",
        target_count=10,
    )
    workspace = DomainWorkspace(
        workspace_id=workspace_id,
        name="Alpha test",
        domain="semiconductors",
        universe_id=universe_id,
        graph_version_id=GRAPH_ID,
    )
    dependencies.workspace_repository.put_universe(universe)  # type: ignore[attr-defined]
    dependencies.workspace_repository.put(workspace)
    graph = TemporalGraphSnapshot(
        snapshot_id=GRAPH_ID,
        workspace_id=workspace_id,
        universe_id=universe_id,
        universe_instrument_ids=tuple(item.instrument_id for item in instruments),
        published_at=NOW,
        as_of_time=NOW,
        knowledge_time=NOW,
        nodes=tuple(
            GraphNode(node_id=item.instrument_id, kind="instrument", label=item.symbol)
            for item in instruments
        ),
    )
    dependencies.graph_repository.publish(graph)
    if response is not None:
        dependencies.alpha_generator = AlphaGeneratorService(
            AlphaGeneratorAgent(FakeLLMClient(response))
        )
    client = TestClient(create_app(dependencies))
    return client, dependencies, graph


def bind_feature(
    dependencies, graph, *, available_at=NOW, status="ready", binding_version=1
):
    return dependencies.feature_bindings.put_binding(
        WorkspaceFeatureBinding(
            version=binding_version,
            workspace_id=WORKSPACE_ID,
            feature_id=FEATURE,
            feature_version=1,
            status=status,
            reason="fixture data unavailable" if status != "ready" else "",
            observation_count=5 if status == "ready" else 0,
            dataset_version_id="market-daily-v1",
            available_at=available_at,
        )
    )


def request_payload(**updates):
    payload = {
        "intent": "test a relationship",
        "feature_names": [FEATURE],
        "universe_id": UNIVERSE_ID,
        "graph_snapshot_id": GRAPH_ID,
        "portfolio": {},
        "risk": {},
        "experiment_id": "alpha-test",
        "trial_limit": 1,
    }
    return {**payload, **updates}


def test_workspace_catalog_reports_unavailable_until_explicit_binding_exists():
    client, _, _ = setup_client()
    response = client.get(f"/api/workspaces/{WORKSPACE_ID}/features")
    item = next(item for item in response.json()["features"] if item["name"] == FEATURE)
    assert item["available"] is False
    assert item["version"] == 1
    assert item["reason"]


def test_future_feature_data_is_unavailable_for_generation():
    client, dependencies, graph = setup_client()
    bind_feature(dependencies, graph, available_at=NOW + timedelta(days=1))
    response = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates", json=request_payload()
    )
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]


def test_later_binding_version_can_refresh_readiness_without_mutating_history():
    client, dependencies, graph = setup_client(
        {
            "candidates": [
                {"id": "one", "expression": "Rank(close_return)", "rationale": "one"}
            ]
        }
    )
    first = bind_feature(dependencies, graph, status="unavailable", binding_version=1)
    second = bind_feature(dependencies, graph, status="ready", binding_version=2)

    bindings = dependencies.feature_bindings.list_bindings(WORKSPACE_ID)
    assert bindings == (first, second)
    catalog = client.get(f"/api/workspaces/{WORKSPACE_ID}/features")
    item = next(item for item in catalog.json()["features"] if item["name"] == FEATURE)
    assert item["available"] is True
    generated = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates", json=request_payload()
    )
    assert generated.status_code == 200
    assert len(generated.json()["candidates"]) == 1


def test_graph_workspace_or_universe_mismatch_is_rejected():
    client, dependencies, graph = setup_client()
    bind_feature(dependencies, graph)
    other = graph.model_copy(update={"snapshot_id": "other", "workspace_id": "other-workspace"})
    dependencies.graph_repository.publish(other)
    response = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates",
        json=request_payload(graph_snapshot_id="other"),
    )
    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


def test_generation_deduplicates_canonical_formulas_and_obeys_trial_cap():
    client, dependencies, graph = setup_client(
        {
            "candidates": [
                {"id": "one", "expression": "Rank(close_return)", "rationale": "one"},
                {"id": "two", "expression": "Rank( close_return )", "rationale": "two"},
                {"id": "three", "expression": "Neg(close_return)", "rationale": "three"},
            ]
        }
    )
    bind_feature(dependencies, graph)
    response = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates", json=request_payload()
    )
    data = response.json()
    assert response.status_code == 200
    assert len(data["candidates"]) == 1
    assert data["trial_count"] == 1
    assert any("duplicate candidate" in reason for reason in data["rejected"])
    assert any("trial limit" in reason for reason in data["rejected"])


def test_malformed_model_output_returns_safe_error_without_provider_text():
    client, dependencies, graph = setup_client({"candidates": "not-an-array secret-value"})
    bind_feature(dependencies, graph)
    response = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/alpha-candidates", json=request_payload()
    )
    assert response.status_code == 502
    assert "secret-value" not in response.text


def test_strategy_validation_and_versions_are_immutable():
    client, dependencies, graph = setup_client()
    bind_feature(dependencies, graph)
    payload = {
        "workspace_id": WORKSPACE_ID,
        "name": "Return rank",
        "expression": "Rank(close_return)",
        "feature_names": [FEATURE],
        "universe_id": UNIVERSE_ID,
        "graph_snapshot_id": GRAPH_ID,
        "portfolio": {"weighting": "equal_weight"},
        "risk": {},
    }
    validated = client.post("/api/strategies/validate", json=payload)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["backtest_performed"] is False
    first_response = client.post(f"/api/workspaces/{WORKSPACE_ID}/strategies", json=payload)
    assert first_response.status_code == 201, first_response.text
    first = first_response.json()
    second_response = client.post(
        f"/api/workspaces/{WORKSPACE_ID}/strategies",
        json={**payload, "strategy_id": first["strategy_id"], "expression": "Neg(close_return)"},
    )
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    history = client.get(f"/api/strategies/{first['strategy_id']}/versions")
    assert history.status_code == 200, history.text
    versions = history.json()["versions"]
    assert (first["version"], second["version"]) == (1, 2)
    assert [item["signal_expression"] for item in versions] == [
        "Rank(close_return)",
        "Neg(close_return)",
    ]
