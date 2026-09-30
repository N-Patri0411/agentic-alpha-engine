"""Point-in-time graph features that can be evaluated by the paper backtest.

This module intentionally exposes a small bridge: a reviewed graph snapshot is
converted into rows with the same schema as a hand-authored factor file.  The
result is a scenario diagnostic, not a return forecast.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .data import PointInTimeViolation, parse_as_of
from .graph_registry import GraphSnapshot, RippleRiskScorer


@dataclass(frozen=True)
class GraphFeatureReceipt:
    """Stable provenance for one graph-to-factor conversion."""

    snapshot_id: str
    snapshot_sha256: str
    feature_name: str
    shock_entity_id: str
    as_of_time: datetime
    row_count: int
    receipt_sha256: str


def _snapshot_digest(snapshot: GraphSnapshot) -> str:
    return snapshot.edges_sha256


def _availability(snapshot: GraphSnapshot) -> datetime:
    """Conservative availability: all evidence and review must be visible."""

    values = [snapshot.created_at]
    for edge in snapshot.edges:
        values.extend((edge.evidence.filing_date, edge.review.reviewed_at))
    return max(values)


def graph_ripple_factors(
    snapshot: GraphSnapshot,
    *,
    dates: Iterable[datetime | pd.Timestamp | str],
    tickers: Iterable[str],
    ticker_to_entity: Mapping[str, str] | None = None,
    shock_entity_id: str,
    as_of_time: datetime,
    feature_name: str = "graph_ripple_risk",
) -> tuple[pd.DataFrame, GraphFeatureReceipt]:
    """Build a point-in-time factor frame from strongest graph shock paths.

    The score is propagated severity from a unit shock and is therefore a
    transparent risk diagnostic.  Rows are omitted before the snapshot became
    available or when the edge was not effective on that date.  A caller may
    negate the score in a formula candidate if testing a defensive ranking.
    """

    as_of = parse_as_of(as_of_time)
    available_at = _availability(snapshot)
    if available_at > as_of:
        raise PointInTimeViolation(
            f"graph snapshot {snapshot.snapshot_id!r} was unavailable as of {as_of.isoformat()}"
        )
    ticker_map = dict(ticker_to_entity or {ticker: ticker for ticker in tickers})
    dates_normalized = [pd.Timestamp(date).to_pydatetime() for date in dates]
    rows: list[dict[str, object]] = []
    for date in sorted(set(dates_normalized)):
        if date.tzinfo is None:
            raise ValueError("feature dates must include a timezone offset")
        if date > as_of:
            raise PointInTimeViolation(
                f"feature date {date.isoformat()} is after requested as-of {as_of.isoformat()}"
            )
        if date < available_at:
            raise PointInTimeViolation(
                f"graph snapshot {snapshot.snapshot_id!r} was unavailable on {date.isoformat()}"
            )
        point = date
        impacts = RippleRiskScorer(snapshot).score(
            shock_entity_id=shock_entity_id,
            severity=1.0,
            as_of_time=point,
            relationship_types={
                "manufacturing_dependency",
                "equipment_dependency",
                "packaging_dependency",
            },
        )
        scores = {impact.entity: impact.severity for impact in impacts.impacts}
        for ticker in sorted(ticker_map):
            entity_id = ticker_map[ticker]
            rows.append(
                {
                    "date": pd.Timestamp(date).tz_convert("UTC").tz_localize(None),
                    "ticker": ticker,
                    "score": float(scores.get(entity_id, 0.0)),
                    "available_at": available_at,
                }
            )
    frame = pd.DataFrame(rows, columns=["date", "ticker", "score", "available_at"])
    canonical = json.dumps(
        {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_sha256": _snapshot_digest(snapshot),
            "feature_name": feature_name,
            "shock_entity_id": shock_entity_id,
            "as_of_time": as_of.isoformat(),
            "rows": frame.astype({"date": str, "available_at": str}).to_dict(orient="records"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    receipt = GraphFeatureReceipt(
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=_snapshot_digest(snapshot),
        feature_name=feature_name,
        shock_entity_id=shock_entity_id,
        as_of_time=as_of,
        row_count=len(frame),
        receipt_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    return frame, receipt
