from datetime import UTC, datetime, timedelta
from pathlib import Path

from alpha_workbench.agents.graph_adjudicator import GraphAdjudicatorAgent
from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot
from alpha_workbench.llm.models import FakeLLMClient

REGISTRY = Path("data/entities/semiconductor_v1.json")
SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
AVAILABLE_AT = datetime(2026, 5, 1, tzinfo=UTC)


def _observation(
    *,
    tier: str = "primary",
    source_url: str = "https://example.test/evidence",
    downstream_entity_id: str = "NVDA",
    downstream_name: str = "NVIDIA",
) -> EvidenceObservation:
    text = f"{downstream_name} relies on TSMC to manufacture advanced products."
    return EvidenceObservation(
        idempotency_key=f"observation:{tier}:{source_url}",
        document=SourceDocument(
            source_kind="sec_filing" if tier == "primary" else "web_discovery",
            source_tier=tier,  # type: ignore[arg-type]
            source_adapter="fixture",
            source_url=source_url,
            content_sha256="f" * 64,
            issuer_entity_id=downstream_entity_id,
            observed_at=AVAILABLE_AT,
            available_at=AVAILABLE_AT,
            retrieved_at=AVAILABLE_AT,
            usage_note="fixture evidence",
        ),
        mentioned_entity_ids=(downstream_entity_id,),
        payload=TextEvidence(
            text=text,
            exact_quote=text,
            character_start=0,
            character_end=len(text),
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="fixture-run"
        ),
    )


def _agent(response: dict[str, object]) -> GraphAdjudicatorAgent:
    registry = EntityRegistry.from_json(REGISTRY)
    return GraphAdjudicatorAgent(FakeLLMClient(response), registry, GraphPublisher(registry))


def test_adjudicator_resolves_alias_and_applies_bounded_state_update() -> None:
    observation = _observation()
    response = {
        "action": "update_state",
        "upstream_entity_id": "TSM",
        "downstream_entity_id": "NVDA",
        "relationship_type": "manufacturing_dependency",
        "state_delta": {"dependency_strength": 1.0, "substitutability": -1.0},
        "supporting_observation_ids": [str(observation.observation_id)],
        "rationale": "The source explicitly confirms the manufacturing dependency.",
    }
    snapshot, report = _agent(response).adjudicate(
        observations=[observation],
        current_snapshot=GraphSnapshot.from_json(SNAPSHOT),
        as_of_time=AVAILABLE_AT,
        next_snapshot_id="fixture-next",
    )

    edge = next(edge for edge in snapshot.edges if edge.edge_id.startswith("tsm-to-nvda"))
    assert edge.dependency_strength == 0.75 + 0.20
    assert edge.substitutability == 0.35 - 0.20
    assert edge.review.reviewed_by == "graph_adjudicator_agent"
    assert report.published_snapshot_id == "fixture-next"


def test_single_discovery_result_cannot_auto_publish_new_edge() -> None:
    observation = _observation(tier="discovery")
    response = {
        "action": "approve_edge",
        "upstream_entity_id": "TSM",
        "downstream_entity_id": "NVDA",
        "relationship_type": "manufacturing_dependency",
        "supporting_observation_ids": [str(observation.observation_id)],
        "rationale": "A discovery result mentions the relationship.",
    }
    current = GraphSnapshot.from_json(SNAPSHOT)
    snapshot, report = _agent(response).adjudicate(
        observations=[observation],
        current_snapshot=current,
        as_of_time=AVAILABLE_AT,
        next_snapshot_id="fixture-discovery-hold",
    )

    assert snapshot.edges == current.edges
    assert report.decisions[0].action == "hold"


def test_two_discovery_sources_can_support_an_auto_published_edge() -> None:
    first = _observation(
        tier="discovery",
        source_url="https://one.example.test/article",
        downstream_entity_id="MU",
        downstream_name="Micron",
    )
    second = _observation(
        tier="discovery",
        source_url="https://two.example.test/article",
        downstream_entity_id="MU",
        downstream_name="Micron",
    )
    response = {
        "action": "approve_edge",
        "upstream_entity_id": "TSM",
        "downstream_entity_id": "MU",
        "relationship_type": "manufacturing_dependency",
        "supporting_observation_ids": [
            str(first.observation_id),
            str(second.observation_id),
        ],
        "rationale": "Independent discovery sources corroborate the relationship.",
    }
    current = GraphSnapshot.from_json(SNAPSHOT)
    snapshot, report = _agent(response).adjudicate(
        observations=[first, second],
        current_snapshot=current,
        as_of_time=AVAILABLE_AT,
        next_snapshot_id="fixture-discovery-approved",
    )

    assert len(snapshot.edges) == len(current.edges) + 1
    assert report.decisions[0].action == "approve_edge"


def test_adjudicator_publishes_a_new_snapshot_only_once(tmp_path: Path) -> None:
    observation = _observation()
    response = {
        "action": "update_state",
        "upstream_entity_id": "TSM",
        "downstream_entity_id": "NVDA",
        "relationship_type": "manufacturing_dependency",
        "supporting_observation_ids": [str(observation.observation_id)],
        "rationale": "The source confirms the active relationship.",
    }
    target = tmp_path / "next.json"
    agent = _agent(response)
    report = agent.adjudicate_and_publish(
        observations=[observation],
        current_snapshot=GraphSnapshot.from_json(SNAPSHOT),
        as_of_time=AVAILABLE_AT,
        next_snapshot_id="fixture-published",
        snapshot_path=target,
    )

    assert target.exists()
    assert report.published_snapshot_id == "fixture-published"


def test_adjudicator_normalizes_only_documented_model_aliases() -> None:
    normalized = GraphAdjudicatorAgent._normalize_model_response(
        {"action": "approve", "state_delta": 0.6}
    )

    assert normalized == {
        "action": "approve_edge",
        "state_delta": {"dependency_strength": 0.6},
    }


def test_adjudicator_decays_state_and_holds_future_observations() -> None:
    current = GraphSnapshot.from_json(SNAPSHOT).model_copy(update={"created_at": AVAILABLE_AT})
    future_observation = _observation()
    future_observation = future_observation.model_copy(
        update={
            "document": future_observation.document.model_copy(
                update={"available_at": AVAILABLE_AT + timedelta(days=181)}
            )
        }
    )
    snapshot, report = _agent({}).adjudicate(
        observations=[future_observation],
        current_snapshot=current,
        as_of_time=AVAILABLE_AT + timedelta(days=180),
        next_snapshot_id="fixture-decayed",
    )

    edge = next(edge for edge in snapshot.edges if edge.edge_id.startswith("tsm-to-nvda"))
    assert edge.freshness == 0.5
    assert future_observation.observation_id in report.held_observation_ids
