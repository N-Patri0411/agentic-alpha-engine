"""Leakage-safe historical panels for comparing graph versions.

The panel is a research join, not an alpha claim.  It selects the latest graph
snapshot that was available when each price bar became available, then records
the next observed close as a clearly-labelled outcome.  The outcome is never
used to construct the graph score.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from .data import PointInTimeViolation, parse_as_of
from .graph_registry import GraphSnapshot, RippleRiskScorer

HistoricalPanelMode = Literal["evolving", "static"]
_REQUIRED_PRICE_COLUMNS = {"date", "ticker", "close", "available_at"}


@dataclass(frozen=True)
class HistoricalPanelReceipt:
    """Reproducibility receipt for one static or evolving panel."""

    schema_version: str
    mode: HistoricalPanelMode
    as_of_time: datetime
    input_snapshot_ids: tuple[str, ...]
    selected_snapshot_ids: tuple[str, ...]
    candidate_price_rows: int
    selected_price_rows: int
    output_rows: int
    excluded_future_price_rows: int
    excluded_unavailable_graph_rows: int
    receipt_sha256: str


@dataclass(frozen=True)
class HistoricalGraphPanel:
    """Panel rows plus immutable input-selection metadata."""

    rows: pd.DataFrame
    receipt: HistoricalPanelReceipt


@dataclass(frozen=True)
class HistoricalPanelComparison:
    """Static and evolving panels aligned for transparent score comparison."""

    static: HistoricalGraphPanel
    evolving: HistoricalGraphPanel
    comparison: pd.DataFrame


def _snapshot_available_at(snapshot: GraphSnapshot) -> datetime:
    """Return the conservative time when a snapshot can be consumed."""

    values = [snapshot.created_at]
    for edge in snapshot.edges:
        values.extend((edge.evidence.filing_date, edge.review.reviewed_at))
    return max(values)


def _normalise_price_frame(prices: pd.DataFrame) -> pd.DataFrame:
    missing = _REQUIRED_PRICE_COLUMNS.difference(prices.columns)
    if missing:
        raise ValueError(f"prices are missing columns: {sorted(missing)}")
    frame = prices.copy()
    frame["ticker"] = frame["ticker"].astype(str)
    frame["date"] = pd.to_datetime(frame["date"])
    if frame["date"].dt.tz is not None:
        frame["date"] = frame["date"].dt.tz_convert("UTC").dt.tz_localize(None)
    frame["date"] = frame["date"].dt.normalize()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    if frame[["ticker", "date"]].duplicated().any():
        raise ValueError("prices must contain one row per ticker and date")
    return frame.sort_values(["ticker", "date"]).reset_index(drop=True)


def _select_snapshot(
    snapshots: Sequence[GraphSnapshot],
    *,
    point_available_at: pd.Timestamp,
    mode: HistoricalPanelMode,
    static_snapshot: GraphSnapshot | None,
) -> GraphSnapshot | None:
    if mode == "static":
        if static_snapshot is None:
            raise ValueError("static mode requires a static_snapshot_id")
        return (
            static_snapshot
            if _snapshot_available_at(static_snapshot) <= point_available_at.to_pydatetime()
            else None
        )
    eligible = [
        snapshot
        for snapshot in snapshots
        if _snapshot_available_at(snapshot) <= point_available_at.to_pydatetime()
    ]
    return max(eligible, key=lambda item: _snapshot_available_at(item)) if eligible else None


def build_historical_graph_panel(
    snapshots: Sequence[GraphSnapshot],
    prices: pd.DataFrame,
    *,
    shock_entity_id: str,
    ticker_to_entity: Mapping[str, str] | None = None,
    as_of_time: datetime,
    mode: HistoricalPanelMode = "evolving",
    static_snapshot_id: str | None = None,
    relationship_types: set[str] | None = None,
) -> HistoricalGraphPanel:
    """Join graph scores to prices using only information available at each bar.

    ``evolving`` selects the latest available snapshot independently for every
    price bar. ``static`` reuses the explicitly selected snapshot.  The
    resulting ``forward_return`` and ``label_available_at`` columns are outcomes
    for evaluation; they are not inputs to the graph score.
    """

    if not snapshots:
        raise ValueError("at least one graph snapshot is required")
    as_of = parse_as_of(as_of_time)
    by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    if len(by_id) != len(snapshots):
        raise ValueError("graph snapshot IDs must be unique")
    if any(_snapshot_available_at(snapshot) > as_of for snapshot in snapshots):
        raise PointInTimeViolation("a graph snapshot is unavailable at the requested as-of time")
    static_snapshot = None
    if static_snapshot_id is not None:
        static_snapshot = by_id.get(static_snapshot_id)
        if static_snapshot is None:
            raise ValueError(f"unknown static_snapshot_id: {static_snapshot_id}")
    frame = _normalise_price_frame(prices)
    candidate_count = len(frame)
    eligible_prices = frame.loc[frame["available_at"] <= pd.Timestamp(as_of)].copy()
    excluded_future = candidate_count - len(eligible_prices)
    ticker_map = dict(ticker_to_entity or {ticker: ticker for ticker in frame["ticker"].unique()})
    if set(eligible_prices["ticker"]) - ticker_map.keys():
        raise ValueError("ticker_to_entity must map every selected ticker")

    rows: list[dict[str, object]] = []
    unavailable_graph_rows = 0
    selected_snapshot_ids: set[str] = set()
    score_cache: dict[tuple[str, str], dict[str, float]] = {}
    for price in eligible_prices.itertuples(index=False):
        available_at = pd.Timestamp(price.available_at)
        snapshot = _select_snapshot(
            snapshots,
            point_available_at=available_at,
            mode=mode,
            static_snapshot=static_snapshot,
        )
        if snapshot is None:
            unavailable_graph_rows += 1
            continue
        selected_snapshot_ids.add(snapshot.snapshot_id)
        cache_key = (snapshot.snapshot_id, available_at.isoformat())
        scores = score_cache.get(cache_key)
        if scores is None:
            result = RippleRiskScorer(snapshot).score(
                shock_entity_id=shock_entity_id,
                severity=1.0,
                as_of_time=available_at.to_pydatetime(),
                relationship_types=relationship_types,
            )
            scores = {impact.entity: float(impact.severity) for impact in result.impacts}
            score_cache[cache_key] = scores
        graph_available_at = _snapshot_available_at(snapshot)
        rows.append(
            {
                "date": price.date,
                "ticker": price.ticker,
                "close": float(price.close),
                "score": scores.get(ticker_map[price.ticker], 0.0),
                "available_at": graph_available_at,
                "price_available_at": price.available_at,
                "graph_snapshot_id": snapshot.snapshot_id,
            }
        )

    result_frame = pd.DataFrame(
        rows,
        columns=[
            "date",
            "ticker",
            "close",
            "score",
            "available_at",
            "price_available_at",
            "graph_snapshot_id",
        ],
    )
    if not result_frame.empty:
        result_frame = result_frame.sort_values(["ticker", "date"]).reset_index(drop=True)
        grouped = result_frame.groupby("ticker", sort=False)
        result_frame["next_close"] = grouped["close"].shift(-1)
        result_frame["label_available_at"] = grouped["price_available_at"].shift(-1)
        result_frame["forward_return"] = result_frame["next_close"] / result_frame["close"] - 1
        result_frame = result_frame.sort_values(["date", "ticker"]).reset_index(drop=True)
    canonical_rows = result_frame.astype(object).where(pd.notna(result_frame), None).to_dict(
        orient="records"
    )
    canonical = json.dumps(
        {
            "mode": mode,
            "as_of_time": as_of.isoformat(),
            "snapshot_ids": sorted(selected_snapshot_ids),
            "rows": canonical_rows,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    receipt = HistoricalPanelReceipt(
        schema_version="1",
        mode=mode,
        as_of_time=as_of,
        input_snapshot_ids=tuple(snapshot.snapshot_id for snapshot in snapshots),
        selected_snapshot_ids=tuple(sorted(selected_snapshot_ids)),
        candidate_price_rows=candidate_count,
        selected_price_rows=len(eligible_prices),
        output_rows=len(result_frame),
        excluded_future_price_rows=excluded_future,
        excluded_unavailable_graph_rows=unavailable_graph_rows,
        receipt_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    return HistoricalGraphPanel(rows=result_frame, receipt=receipt)


def compare_static_and_evolving(
    snapshots: Sequence[GraphSnapshot],
    prices: pd.DataFrame,
    *,
    shock_entity_id: str,
    static_snapshot_id: str,
    ticker_to_entity: Mapping[str, str] | None = None,
    as_of_time: datetime,
    relationship_types: set[str] | None = None,
) -> HistoricalPanelComparison:
    """Build aligned panels and expose the score change caused by graph updates."""

    common = {
        "snapshots": snapshots,
        "prices": prices,
        "shock_entity_id": shock_entity_id,
        "ticker_to_entity": ticker_to_entity,
        "as_of_time": as_of_time,
        "relationship_types": relationship_types,
    }
    static = build_historical_graph_panel(
        **common, mode="static", static_snapshot_id=static_snapshot_id
    )
    evolving = build_historical_graph_panel(**common, mode="evolving")
    left = static.rows[["date", "ticker", "score"]].rename(columns={"score": "static_score"})
    right = evolving.rows[["date", "ticker", "score"]].rename(
        columns={"score": "evolving_score"}
    )
    comparison = left.merge(right, on=["date", "ticker"], how="outer", validate="one_to_one")
    comparison["score_delta"] = comparison["evolving_score"] - comparison["static_score"]
    return HistoricalPanelComparison(static=static, evolving=evolving, comparison=comparison)
