from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.candidate_graph import CandidateGraphBuilder, DiscoveredRelationship
from alpha_workbench.graph_registry import EntityRegistry, GraphSnapshot
from alpha_workbench.graph_visualizer import render_candidate_graph_html, render_graph_html

REGISTRY = Path("data/entities/semiconductor_v1.json")
SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")


def test_visualizer_renders_all_ten_registry_nodes_and_snapshot_edges(tmp_path: Path) -> None:
    output = tmp_path / "semiconductor-graph.html"

    receipt = render_graph_html(
        registry=EntityRegistry.from_json(REGISTRY),
        snapshot=GraphSnapshot.from_json(SNAPSHOT),
        output_path=output,
    )

    page = output.read_text(encoding="utf-8")
    assert receipt.node_count == 10
    assert receipt.edge_count == 2
    assert ">TSM<" in page
    assert ">ASML<" in page
    assert ">AMAT<" in page
    assert "TSM &rarr; NVDA" in page
    assert "manufacturing_dependency" in page
    assert "Selected relationship details" in page
    assert "Substitutability" in page
    assert "data-edge-id" in page
    assert '<tr class="edge" data-edge-id=' in page


def test_candidate_visualizer_exposes_anchors_provenance_and_all_candidate_types(
    tmp_path: Path,
) -> None:
    registry = EntityRegistry.from_json(REGISTRY)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    relationship = DiscoveredRelationship(
        source_entity_name="NVIDIA", target_entity_name="AMD",
        relationship_type="competitive_substitution",
        evidence_quote="NVIDIA competes with AMD in AI accelerators",
        passage_text="NVIDIA competes with AMD in AI accelerators.",
        source_url="https://example.test/discovery", available_at=now,
        rationale="discovery summary candidate", suggested_confidence=0.35,
        source_tier="discovery", source_kind="web_discovery", source_adapter="fixture",
        observation_id="obs-1", evidence_basis="discovery_summary",
    )
    candidate_graph = CandidateGraphBuilder(registry).build([relationship])
    output = tmp_path / "candidate-graph.html"
    receipt = render_candidate_graph_html(candidate_graph=candidate_graph, output_path=output)
    page = output.read_text(encoding="utf-8")
    assert receipt.node_count == 10
    assert receipt.edge_count == 1
    assert "ASML" in page  # isolated anchors remain visible
    assert "competitive_substitution" in page
    assert "discovery / web_discovery" in page
    assert "discovery_summary" in page
    assert "NVIDIA competes with AMD" in page
