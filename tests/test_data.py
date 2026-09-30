from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from alpha_workbench.data import (
    FrozenCSVMarketDataProvider,
    PointInTimeViolation,
    assert_available_as_of,
    market_bars_to_prices,
    parse_as_of,
)
from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    MarketBar,
    SourceDocument,
)


def _bar_observation(
    *, available_at: datetime, bar_start: datetime, key: str
) -> EvidenceObservation:
    return EvidenceObservation(
        idempotency_key=key,
        document=SourceDocument(
            source_kind="market_data", source_tier="market_data", source_adapter="fixture",
            source_url="https://example.test/bars", content_sha256="a" * 64,
            issuer_entity_id="NVDA", observed_at=available_at, available_at=available_at,
            retrieved_at=available_at, usage_note="fixture",
        ),
        mentioned_entity_ids=("NVDA",),
        payload=MarketBar(
            symbol="NVDA", bar_start=bar_start, bar_end=bar_start.replace(hour=21),
            open=100, high=102, low=99, close=101, volume=1,
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="bars"
        ),
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


def test_market_bars_to_prices_filters_future_and_preserves_receipt() -> None:
    as_of = datetime(2026, 9, 2, 21, tzinfo=UTC)
    early = _bar_observation(
        available_at=datetime(2026, 9, 2, 20, tzinfo=UTC),
        bar_start=datetime(2026, 9, 2, tzinfo=UTC), key="early",
    )
    future = _bar_observation(
        available_at=datetime(2026, 9, 3, tzinfo=UTC),
        bar_start=datetime(2026, 9, 3, tzinfo=UTC), key="future",
    )
    result = market_bars_to_prices([early, future], as_of_time=as_of)
    assert list(result.prices.columns) == ["date", "ticker", "close", "available_at"]
    assert len(result.prices) == 1
    assert result.receipt.excluded_future_count == 1
    assert result.receipt.selected_observation_ids == [str(early.observation_id)]


def test_market_bars_to_prices_deduplicates_deterministically() -> None:
    day = datetime(2026, 9, 2, tzinfo=UTC)
    first = _bar_observation(
        available_at=datetime(2026, 9, 2, 20, tzinfo=UTC), bar_start=day, key="first"
    )
    second = _bar_observation(
        available_at=datetime(2026, 9, 2, 21, tzinfo=UTC), bar_start=day, key="second"
    )
    result = market_bars_to_prices([first, second], as_of_time=datetime(2026, 9, 3, tzinfo=UTC))
    assert len(result.prices) == 1
    assert result.receipt.selected_observation_ids == [str(second.observation_id)]
