from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from alpha_workbench.graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot
from alpha_workbench.historical_panel import (
    HistoricalGraphPanel,
    build_historical_graph_panel,
    compare_static_and_evolving,
)

SNAPSHOT_PATH = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
REGISTRY_PATH = Path("data/entities/semiconductor_v1.json")


def _snapshots() -> tuple[GraphSnapshot, GraphSnapshot]:
    first = GraphSnapshot.from_json(SNAPSHOT_PATH)
    changed_edge = first.edges[0].model_copy(update={"dependency_strength": 0.95})
    second = GraphPublisher(EntityRegistry.from_json(REGISTRY_PATH)).build_snapshot(
        snapshot_id="semiconductor-sec-reviewed-v2",
        created_at=datetime(2026, 9, 5, 19, 30, tzinfo=UTC),
        edges=[changed_edge, first.edges[1]],
    )
    return first, second


def _prices() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    closes = {
        "2026-09-01": {"NVDA": 100.0, "AMD": 80.0},
        "2026-09-02": {"NVDA": 101.0, "AMD": 79.0},
        "2026-09-05": {"NVDA": 98.0, "AMD": 81.0},
        "2026-09-06": {"NVDA": 99.0, "AMD": 82.0},
        "2026-10-01": {"NVDA": 120.0, "AMD": 90.0},
    }
    for date, ticker_closes in closes.items():
        for ticker, close in ticker_closes.items():
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "close": close,
                    "available_at": f"{date}T21:00:00Z",
                }
            )
    return pd.DataFrame(rows)


def _row(panel: HistoricalGraphPanel, date: str, ticker: str) -> pd.Series:
    return panel.rows.loc[
        (panel.rows["date"] == pd.Timestamp(date)) & (panel.rows["ticker"] == ticker)
    ].iloc[0]


def test_evolving_panel_uses_only_snapshot_available_at_each_price_bar() -> None:
    first, second = _snapshots()
    panel = build_historical_graph_panel(
        [first, second],
        _prices(),
        shock_entity_id="TSM",
        ticker_to_entity={"NVDA": "NVDA", "AMD": "AMD"},
        as_of_time=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert panel.receipt.excluded_future_price_rows == 2
    assert panel.receipt.selected_snapshot_ids == (
        "semiconductor-sec-reviewed-v1",
        "semiconductor-sec-reviewed-v2",
    )
    before_update = _row(panel, "2026-09-01", "NVDA")
    after_update = _row(panel, "2026-09-05", "NVDA")
    assert before_update["graph_snapshot_id"] == first.snapshot_id
    assert after_update["graph_snapshot_id"] == second.snapshot_id
    assert after_update["score"] > before_update["score"]
    assert panel.rows["forward_return"].notna().sum() > 0


def test_static_panel_does_not_look_ahead_to_later_graph_snapshot() -> None:
    first, second = _snapshots()
    panel = build_historical_graph_panel(
        [first, second],
        _prices(),
        shock_entity_id="TSM",
        ticker_to_entity={"NVDA": "NVDA", "AMD": "AMD"},
        as_of_time=datetime(2026, 9, 10, tzinfo=UTC),
        mode="static",
        static_snapshot_id=first.snapshot_id,
    )
    assert set(panel.rows["graph_snapshot_id"]) == {first.snapshot_id}
    assert _row(panel, "2026-09-05", "NVDA")["score"] < 0.95


def test_comparison_exposes_graph_update_score_delta() -> None:
    first, second = _snapshots()
    comparison = compare_static_and_evolving(
        [first, second],
        _prices(),
        shock_entity_id="TSM",
        static_snapshot_id=first.snapshot_id,
        ticker_to_entity={"NVDA": "NVDA", "AMD": "AMD"},
        as_of_time=datetime(2026, 9, 10, tzinfo=UTC),
    ).comparison
    updated = comparison.loc[
        (comparison["date"] == pd.Timestamp("2026-09-05"))
        & (comparison["ticker"] == "NVDA")
    ].iloc[0]
    assert updated["evolving_score"] > updated["static_score"]
    assert updated["score_delta"] > 0
