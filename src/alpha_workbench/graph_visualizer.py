"""Deterministic, local HTML rendering for a reviewed graph snapshot."""
# ruff: noqa: E501

from __future__ import annotations

import json
from html import escape
from pathlib import Path

import networkx as nx
from pydantic import BaseModel, Field

from .graph_registry import EntityRegistry, GraphSnapshot

_RELATIONSHIP_COLORS = {
    "manufacturing_dependency": "#f97316",
    "equipment_dependency": "#a855f7",
    "packaging_dependency": "#14b8a6",
    "customer_concentration": "#eab308",
    "competitive_substitution": "#ef4444",
    "ip_or_license": "#6366f1",
    "geographic_or_regulatory": "#64748b",
}
_VIEWBOX_WIDTH = 1_200
_VIEWBOX_HEIGHT = 760
_NODE_RADIUS = 27


class GraphRenderReceipt(BaseModel):
    """Small, serializable receipt for a locally generated graph view."""

    snapshot_id: str
    node_count: int = Field(ge=1)
    edge_count: int = Field(ge=0)
    output_path: str


def render_graph_html(
    *, registry: EntityRegistry, snapshot: GraphSnapshot, output_path: Path
) -> GraphRenderReceipt:
    """Render all registry entities and the snapshot's approved edges into HTML.

    NetworkX is used only in this view layer to construct the directed graph and
    calculate a seeded layout. It does not replace the audited JSON contracts or
    participate in graph adjudication/scoring.
    """

    if snapshot.entity_registry_id != registry.registry_id:
        raise ValueError("snapshot entity registry does not match visualization registry")
    graph = nx.DiGraph()
    for entity in registry.entities:
        graph.add_node(
            entity.entity_id,
            label=entity.legal_name,
            tradeable=entity.tradeable,
        )
    for edge in snapshot.edges:
        graph.add_edge(
            edge.upstream_entity_id,
            edge.downstream_entity_id,
            relationship_type=edge.relationship_type,
            dependency_strength=edge.dependency_strength,
            substitutability=edge.substitutability,
            confidence=edge.confidence,
            freshness=edge.freshness,
            capacity_stress=edge.capacity_stress,
            geographic_regulatory_stress=edge.geographic_regulatory_stress,
            evidence_support=edge.evidence_support,
            evidence_url=edge.evidence.source_url,
            edge_id=edge.edge_id,
        )
    raw_positions = nx.spring_layout(graph, seed=20260902, k=1.4, iterations=100)
    positions = {
        str(node_id): (float(position[0]), float(position[1]))
        for node_id, position in raw_positions.items()
    }
    coordinates = _scaled_coordinates(positions)
    edge_details = {
        edge.edge_id: {
            "direction": f"{edge.upstream_entity_id} → {edge.downstream_entity_id}",
            "relationship_type": edge.relationship_type,
            "dependency_strength": edge.dependency_strength,
            "substitutability": edge.substitutability,
            "confidence": edge.confidence,
            "freshness": edge.freshness,
            "capacity_stress": edge.capacity_stress,
            "geographic_regulatory_stress": edge.geographic_regulatory_stress,
            "evidence_support": edge.evidence_support,
            "effective_from": edge.effective_from.isoformat(),
            "effective_to": edge.effective_to.isoformat() if edge.effective_to else "open",
            "source_url": edge.evidence.source_url,
            "evidence_quote": edge.evidence.evidence_quote,
            "reviewed_by": edge.review.reviewed_by,
            "review_decision": edge.review.decision,
            "review_rationale": edge.review.rationale,
        }
        for edge in snapshot.edges
    }
    document = _html_document(graph, coordinates, snapshot.snapshot_id, edge_details)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return GraphRenderReceipt(
        snapshot_id=snapshot.snapshot_id,
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        output_path=str(output_path),
    )


def _scaled_coordinates(
    positions: dict[str, tuple[float, float]]
) -> dict[str, tuple[float, float]]:
    """Place NetworkX's normalized coordinates inside the SVG canvas."""

    margin = 90
    scaled: dict[str, tuple[float, float]] = {}
    for node_id, (x, y) in positions.items():
        scaled[node_id] = (
            margin + (x + 1) / 2 * (_VIEWBOX_WIDTH - 2 * margin),
            margin + (1 - (y + 1) / 2) * (_VIEWBOX_HEIGHT - 2 * margin),
        )
    return scaled


def _html_document(
    graph: nx.DiGraph,
    coordinates: dict[str, tuple[float, float]],
    snapshot_id: str,
    edge_details: dict[str, dict[str, object]],
) -> str:
    edge_svg = "\n".join(
        _edge_svg(graph, source, target, coordinates)
        for source, target in graph.edges
    )
    node_svg = "\n".join(
        _node_svg(graph, node_id, coordinates) for node_id in graph.nodes
    )
    edge_rows = "\n".join(
        _edge_row(graph, source, target) for source, target in graph.edges
    )
    serialized_details = json.dumps(edge_details).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Semiconductor graph — {escape(snapshot_id)}</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, Segoe UI, sans-serif; }}
    body {{ background: #0b1020; color: #e5e7eb; margin: 0; padding: 24px; }}
    main {{ max-width: 1240px; margin: auto; }}
    h1 {{ margin-bottom: 4px; }} p {{ color: #a5b4cc; }}
    .card {{ background: #111936; border: 1px solid #293552; border-radius: 12px; padding: 16px; margin-top: 18px; }}
    svg {{ width: 100%; height: auto; background: #0d142a; border-radius: 8px; }}
    .node-label {{ font-size: 13px; fill: #f8fafc; font-weight: 700; text-anchor: middle; dominant-baseline: middle; }}
    table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; padding: 9px; border-bottom: 1px solid #293552; }}
    a {{ color: #7dd3fc; }} .legend {{ display: flex; gap: 18px; flex-wrap: wrap; font-size: 14px; }}
    .dot {{ display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 5px; }}
    .edge {{ cursor: pointer; }} .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }}
    .metric {{ background: #0d142a; border-radius: 7px; padding: 9px; }} .metric small {{ color: #94a3b8; display: block; }}
    blockquote {{ border-left: 3px solid #38bdf8; color: #cbd5e1; margin: 14px 0; padding-left: 12px; }}
  </style>
</head>
<body><main>
  <h1>Semiconductor relationship graph</h1>
  <p>Snapshot <code>{escape(snapshot_id)}</code>. Solid nodes are tradeable instruments; outlined nodes are relevant non-tradeable companies. Isolated nodes are intentional: no approved relationship exists yet.</p>
  <section class="card">
    <div class="legend"><span><i class="dot" style="background:#2563eb"></i>Tradeable</span><span><i class="dot" style="background:#16a34a"></i>Non-tradeable</span><span><i class="dot" style="background:#f97316"></i>Manufacturing dependency</span></div>
    <svg viewBox="0 0 {_VIEWBOX_WIDTH} {_VIEWBOX_HEIGHT}" role="img" aria-label="Directed semiconductor relationship graph">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#cbd5e1" /></marker></defs>
      {edge_svg}
      {node_svg}
    </svg>
  </section>
  <section class="card"><h2>Selected relationship details</h2><p id="edge-detail-empty">Click an arrow or a table row to inspect every numeric state field, evidence, and review receipt.</p><div id="edge-detail" hidden></div></section>
  <section class="card"><h2>Approved relationships in this snapshot</h2>
    <table><thead><tr><th>Direction</th><th>Type</th><th>Strength</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody>{edge_rows}</tbody></table>
  </section>
</main><script>
const edgeDetails = {serialized_details};
function addMetric(parent, label, value) {{
  const item = document.createElement("div"); item.className = "metric";
  const heading = document.createElement("small"); heading.textContent = label;
  const valueNode = document.createElement("strong"); valueNode.textContent = String(value);
  item.append(heading, valueNode); parent.append(item);
}}
function selectEdge(id) {{
  const edge = edgeDetails[id]; if (!edge) return;
  const panel = document.getElementById("edge-detail"); panel.replaceChildren(); panel.hidden = false;
  document.getElementById("edge-detail-empty").hidden = true;
  const title = document.createElement("h3"); title.textContent = edge.direction + " — " + edge.relationship_type; panel.append(title);
  const grid = document.createElement("div"); grid.className = "detail-grid";
  [["Dependency strength", edge.dependency_strength], ["Substitutability", edge.substitutability], ["Confidence", edge.confidence], ["Freshness", edge.freshness], ["Capacity stress", edge.capacity_stress], ["Geographic/regulatory stress", edge.geographic_regulatory_stress], ["Evidence support", edge.evidence_support], ["Effective from", edge.effective_from], ["Effective to", edge.effective_to], ["Review", edge.review_decision + " by " + edge.reviewed_by]].forEach(([label, value]) => addMetric(grid, label, value));
  panel.append(grid);
  const quote = document.createElement("blockquote"); quote.textContent = edge.evidence_quote; panel.append(quote);
  const rationale = document.createElement("p"); rationale.textContent = "Review rationale: " + edge.review_rationale; panel.append(rationale);
  const source = document.createElement("a"); source.href = edge.source_url; source.textContent = "Open evidence source"; panel.append(source);
}}
document.querySelectorAll("[data-edge-id]").forEach((element) => {{ element.addEventListener("click", () => selectEdge(element.dataset.edgeId)); }});
</script></body></html>"""


def _edge_svg(
    graph: nx.DiGraph,
    source: str,
    target: str,
    coordinates: dict[str, tuple[float, float]],
) -> str:
    source_x, source_y = coordinates[source]
    target_x, target_y = coordinates[target]
    relationship_type = str(graph.edges[source, target]["relationship_type"])
    edge_id = str(graph.edges[source, target]["edge_id"])
    color = _RELATIONSHIP_COLORS[relationship_type]
    title = escape(
        f"{source} → {target}: {relationship_type}; strength "
        f"{graph.edges[source, target]['dependency_strength']:.2f}; confidence "
        f"{graph.edges[source, target]['confidence']:.2f}"
    )
    return (
        f'<line class="edge" data-edge-id="{escape(edge_id, quote=True)}" x1="{source_x:.1f}" y1="{source_y:.1f}" '
        f'x2="{target_x:.1f}" y2="{target_y:.1f}" stroke="{color}" '
        f'stroke-width="4" opacity="0.9" marker-end="url(#arrow)"><title>{title}</title></line>'
    )


def _node_svg(
    graph: nx.DiGraph, node_id: str, coordinates: dict[str, tuple[float, float]]
) -> str:
    x, y = coordinates[node_id]
    attributes = graph.nodes[node_id]
    tradeable = bool(attributes["tradeable"])
    connected = graph.degree[node_id] > 0
    fill = "#2563eb" if tradeable else "#16a34a"
    opacity = "1" if connected else "0.45"
    title = escape(str(attributes["label"]))
    return f"""<g opacity="{opacity}"><title>{title}</title>
      <circle cx="{x:.1f}" cy="{y:.1f}" r="{_NODE_RADIUS}" fill="{fill}" stroke="#e2e8f0" stroke-width="2" />
      <text class="node-label" x="{x:.1f}" y="{y:.1f}">{escape(node_id)}</text></g>"""


def _edge_row(graph: nx.DiGraph, source: str, target: str) -> str:
    edge = graph.edges[source, target]
    edge_id = escape(str(edge["edge_id"]), quote=True)
    return (
        f'<tr class="edge" data-edge-id="{edge_id}">'
        f"<td>{escape(source)} &rarr; {escape(target)}</td>"
        f"<td>{escape(str(edge['relationship_type']))}</td>"
        f"<td>{edge['dependency_strength']:.2f}</td>"
        f"<td>{edge['confidence']:.2f}</td>"
        f"<td><a href=\"{escape(str(edge['evidence_url']), quote=True)}\">source</a></td>"
        "</tr>"
    )
