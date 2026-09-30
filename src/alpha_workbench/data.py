"""Frozen market-data adapters and point-in-time validation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from .evidence import EvidenceObservation, MarketBar
from .models import DatasetSnapshot

REQUIRED_PRICE_COLUMNS = {"date", "ticker", "close", "available_at"}
REQUIRED_FACTOR_COLUMNS = {"date", "ticker", "score", "available_at"}


class PointInTimeViolation(ValueError):
    """Raised when a research run attempts to consume unavailable information."""


class LedgerPriceReceipt(BaseModel):
    """Auditable selection receipt without copying raw market-data payloads."""

    as_of_time: datetime
    candidate_market_bar_count: int = Field(ge=0)
    selected_market_bar_count: int = Field(ge=0)
    excluded_future_count: int = Field(ge=0)
    selected_observation_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LedgerPriceSnapshot:
    """Backtest-ready prices and their point-in-time selection receipt."""

    prices: pd.DataFrame
    receipt: LedgerPriceReceipt


def market_bars_to_prices(
    observations: Sequence[EvidenceObservation], *, as_of_time: datetime
) -> LedgerPriceSnapshot:
    """Convert ledger market bars available by ``as_of_time`` to price rows.

    The resulting frame has only ``date``, ``ticker``, ``close``, and
    ``available_at``. Bars unavailable at the requested research time are
    excluded, and duplicate ticker/date rows choose the deterministically latest
    available observation. Observation IDs in the receipt preserve provenance
    without redistributing the source payload.
    """

    as_of = parse_as_of(as_of_time)
    bars = [
        (item, item.payload)
        for item in observations
        if isinstance(item.payload, MarketBar)
    ]
    eligible = [item for item in bars if item[0].document.available_at <= as_of]
    grouped: dict[tuple[str, date], tuple[EvidenceObservation, MarketBar]] = {}
    for item, payload in eligible:
        bar_date = payload.bar_start.astimezone(UTC).date()
        key = (payload.symbol, bar_date)
        previous = grouped.get(key)
        if previous is None or (
            item.document.available_at,
            str(item.observation_id),
        ) > (
            previous[0].document.available_at,
            str(previous[0].observation_id),
        ):
            grouped[key] = (item, payload)
    rows = [
        {
            "date": date,
            "ticker": ticker,
            "close": float(item[1].close),
            "available_at": item[0].document.available_at,
        }
        for (ticker, date), item in grouped.items()
    ]
    frame = pd.DataFrame(rows, columns=["date", "ticker", "close", "available_at"])
    if not frame.empty:
        frame = frame.sort_values(["date", "ticker"]).reset_index(drop=True)
    receipt = LedgerPriceReceipt(
        as_of_time=as_of,
        candidate_market_bar_count=len(bars),
        selected_market_bar_count=len(frame),
        excluded_future_count=len(bars) - len(eligible),
        selected_observation_ids=[
            str(grouped[key][0].observation_id) for key in sorted(grouped)
        ],
    )
    return LedgerPriceSnapshot(prices=frame, receipt=receipt)


def parse_as_of(value: str | datetime) -> datetime:
    """Parse an ISO datetime and require a timezone-aware timestamp."""

    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("as-of timestamps must include a timezone offset")
    return parsed


def assert_available_as_of(frame: pd.DataFrame, as_of_time: datetime) -> None:
    """Reject any observation published after the requested research timestamp."""

    if "available_at" not in frame.columns:
        raise ValueError("data must include an available_at column")
    availability = pd.to_datetime(frame["available_at"], utc=True)
    as_of = pd.Timestamp(as_of_time).tz_convert("UTC")
    leaked = frame.loc[availability > as_of]
    if not leaked.empty:
        identifiers = leaked[[column for column in ("date", "ticker") if column in leaked]].head(3)
        raise PointInTimeViolation(
            f"{len(leaked)} observation(s) were unavailable as of {as_of.isoformat()}: "
            f"{identifiers.to_dict(orient='records')}"
        )


@dataclass(frozen=True)
class FrozenCSVMarketDataProvider:
    """Offline provider for explicit, user-owned CSV fixtures or development data."""

    path: Path
    source_name: str = "local_frozen_csv"

    def load_prices(self, as_of_time: datetime) -> pd.DataFrame:
        """Load price observations that were available by the supplied timestamp."""

        frame = pd.read_csv(self.path)
        missing = REQUIRED_PRICE_COLUMNS.difference(frame.columns)
        if missing:
            raise ValueError(f"price CSV is missing required columns: {sorted(missing)}")
        assert_available_as_of(frame, as_of_time)
        frame["date"] = pd.to_datetime(frame["date"])
        frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
        return frame.sort_values(["date", "ticker"]).reset_index(drop=True)

    def snapshot(self, retrieved_at: datetime) -> DatasetSnapshot:
        """Create a stable provenance record for the exact source file."""

        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        return DatasetSnapshot(
            source=f"{self.source_name}:{self.path.name}",
            content_sha256=digest,
            retrieved_at=retrieved_at,
            usage_note=(
                "Developer fixture or user-provided data; not licensed for redistribution "
                "by default."
            ),
        )


def load_factors(path: Path, as_of_time: datetime) -> pd.DataFrame:
    """Load scored factors and enforce their availability guarantee."""

    frame = pd.read_csv(path)
    missing = REQUIRED_FACTOR_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"factor CSV is missing required columns: {sorted(missing)}")
    assert_available_as_of(frame, as_of_time)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    return frame.sort_values(["date", "ticker"]).reset_index(drop=True)
