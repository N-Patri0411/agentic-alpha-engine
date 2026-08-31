"""Frozen market-data adapters and point-in-time validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .models import DatasetSnapshot

REQUIRED_PRICE_COLUMNS = {"date", "ticker", "close", "available_at"}
REQUIRED_FACTOR_COLUMNS = {"date", "ticker", "score", "available_at"}


class PointInTimeViolation(ValueError):
    """Raised when a research run attempts to consume unavailable information."""


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
