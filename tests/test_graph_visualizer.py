from pathlib import Path

from alpha_workbench.graph_registry import EntityRegistry, GraphSnapshot
from alpha_workbench.graph_visualizer import render_graph_html

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
