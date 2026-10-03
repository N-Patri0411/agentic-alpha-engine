"""Small bounded NetworkX adapter for graph diagnostics, never persistence."""

from __future__ import annotations

from alpha_workbench.temporal_graph.contracts import TemporalGraphSnapshot


class BoundedGraphAnalysis:
    """Centrality, component, and path queries over a snapshot's visible edges."""

    def __init__(
        self, snapshot: TemporalGraphSnapshot, *, max_nodes: int = 2_000, max_edges: int = 20_000
    ) -> None:
        if max_nodes < 1 or max_edges < 0:
            raise ValueError("analysis bounds must be positive")
        if len(snapshot.nodes) > max_nodes or len(snapshot.edge_states) > max_edges:
            raise ValueError("snapshot exceeds bounded analysis limits")
        try:
            import networkx as nx
        except ImportError as exc:
            raise RuntimeError("install the visualization extra to enable graph analysis") from exc
        self._nx = nx
        self._graph = nx.DiGraph()
        self._graph.add_nodes_from(node.node_id for node in snapshot.nodes)
        semantics = {
            relation.relationship_id: relation.semantics for relation in snapshot.relationships
        }
        for edge in snapshot.visible_edge_states():
            if edge.lifecycle_status != "active":
                continue
            self._graph.add_edge(
                edge.source_node_id,
                edge.target_node_id,
                weight=edge.propagation_coefficient,
                relationship_id=edge.relationship_id,
            )
            if semantics[edge.relationship_id] == "symmetric":
                self._graph.add_edge(
                    edge.target_node_id,
                    edge.source_node_id,
                    weight=edge.propagation_coefficient,
                    relationship_id=edge.relationship_id,
                )

    def centrality(self) -> dict[str, float]:
        """Return deterministic weighted-degree centrality normalized by graph size."""
        denominator = max(len(self._graph) - 1, 1)
        return {
            key: round(float(value) / denominator, 12)
            for key, value in sorted(self._graph.degree(weight="weight"))
        }

    def components(self) -> tuple[tuple[str, ...], ...]:
        """Return weakly connected components in stable order."""
        groups = (
            tuple(sorted(group)) for group in self._nx.weakly_connected_components(self._graph)
        )
        return tuple(sorted(groups))

    def path(self, source_node_id: str, target_node_id: str) -> tuple[str, ...] | None:
        """Return shortest directed path, or ``None`` when no path exists."""
        try:
            return tuple(self._nx.shortest_path(self._graph, source_node_id, target_node_id))
        except self._nx.NetworkXNoPath:
            return None
