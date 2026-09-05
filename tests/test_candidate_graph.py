from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.candidate_graph import CandidateGraphBuilder, DiscoveredRelationship
from alpha_workbench.extraction import DocumentPassage, OpenWorldRelationshipExtractor
from alpha_workbench.graph_registry import EntityRegistry
from alpha_workbench.llm.models import FakeLLMClient

REGISTRY = Path("data/entities/semiconductor_v1.json")
NOW = datetime(2026, 9, 4, tzinfo=UTC)
PASSAGE = (
    "Microsoft deploys NVIDIA GPUs in its cloud infrastructure and competes with Apple "
    "in AI services."
)


def _relationship(source: str, target: str, relationship_type: str) -> DiscoveredRelationship:
    return DiscoveredRelationship(
        source_entity_name=source,
        target_entity_name=target,
        relationship_type=relationship_type,  # type: ignore[arg-type]
        evidence_quote=(
            "Microsoft deploys NVIDIA GPUs in its cloud infrastructure"
        ),
        passage_text=PASSAGE,
        source_url="https://example.test/evidence",
        available_at=NOW,
        rationale="fixture",
        suggested_confidence=0.8,
    )


def test_candidate_graph_adds_one_hop_external_node_without_changing_registry() -> None:
    registry = EntityRegistry.from_json(REGISTRY)
    graph = CandidateGraphBuilder(registry).build(
        [_relationship("Microsoft", "NVIDIA", "customer_concentration")]
    )

    microsoft = next(node for node in graph.nodes if node.entity_id == "candidate:microsoft")
    assert microsoft.kind == "discovered"
    assert microsoft.status == "candidate"
    assert graph.edges[0].target_entity_id == "NVDA"
    assert graph.edges[0].scenario_eligible is False
    assert "candidate:microsoft" not in registry.entity_ids


def test_candidate_graph_rejects_relationships_without_an_anchor() -> None:
    graph = CandidateGraphBuilder(EntityRegistry.from_json(REGISTRY)).build(
        [_relationship("Microsoft", "Apple", "competitive_substitution")]
    )

    assert graph.edges == []
    assert graph.ignored_relationship_count == 1


def test_open_world_extractor_keeps_external_names_and_exact_quote() -> None:
    extractor = OpenWorldRelationshipExtractor(
        FakeLLMClient(
            {
                "relationships": [
                    {
                        "source_entity_name": "Microsoft",
                        "target_entity_name": "NVIDIA",
                        "relationship_type": "customer_concentration",
                        "evidence_quote": (
                            "Microsoft deploys NVIDIA GPUs in its cloud infrastructure"
                        ),
                        "rationale": "The passage names a deployment relationship.",
                        "suggested_confidence": 0.8,
                    }
                ]
            }
        ),
        {"NVDA": ("NVIDIA",)},
    )
    result = extractor.extract(
        DocumentPassage(
            snapshot_sha256="a" * 64,
            source_url="https://example.test/evidence",
            start_offset=0,
            end_offset=len(PASSAGE),
            text=PASSAGE,
            matching_keywords=["customer"],
        ),
        available_at=NOW.isoformat(),
    )

    assert result.relationships[0].source_entity_name == "Microsoft"
    assert result.relationships[0].target_entity_name == "NVIDIA"
