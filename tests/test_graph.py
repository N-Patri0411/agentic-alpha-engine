from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.graph import SupplyChainGraph


def test_scenario_propagates_over_effective_paths() -> None:
    graph = SupplyChainGraph.from_json(Path("data/semiconductor_edges.json"))
    result = graph.scenario("TSM", 0.9, datetime(2024, 1, 15, tzinfo=UTC))

    severities = {impact.entity: impact.severity for impact in result.impacts}
    assert severities["NVDA"] == 0.9 * 0.95 * 0.95
    assert severities["AMD"] == 0.9 * 0.9 * 0.92
    assert severities["MSFT"] < severities["NVDA"]


def test_scenario_ignores_edges_before_their_effective_date() -> None:
    graph = SupplyChainGraph.from_json(Path("data/semiconductor_edges.json"))
    result = graph.scenario("TSM", 0.9, datetime(2019, 1, 15, tzinfo=UTC))

    assert result.impacts == []
