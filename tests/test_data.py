from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from alpha_workbench.data import (
    FrozenCSVMarketDataProvider,
    PointInTimeViolation,
    assert_available_as_of,
    parse_as_of,
)


def test_rejects_observations_not_available_at_research_time() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "ticker": ["NVDA"],
            "available_at": ["2024-01-03T21:00:00+00:00"],
        }
    )

    with pytest.raises(PointInTimeViolation):
        assert_available_as_of(frame, datetime(2024, 1, 2, 21, tzinfo=UTC))


def test_as_of_requires_an_explicit_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        parse_as_of("2024-01-02T21:00:00")


def test_frozen_provider_creates_a_repeatable_snapshot() -> None:
    provider = FrozenCSVMarketDataProvider(Path("data/demo_prices.csv"))

    snapshot = provider.snapshot(datetime(2024, 1, 5, 21, tzinfo=UTC))

    assert snapshot.source == "local_frozen_csv:demo_prices.csv"
    assert len(snapshot.content_sha256) == 64
    assert "not licensed for redistribution" in snapshot.usage_note
