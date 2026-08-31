from datetime import UTC, datetime

import pandas as pd
import pytest

from alpha_workbench.backtest import backtest_long_short
from alpha_workbench.data import PointInTimeViolation


def _prices() -> pd.DataFrame:
    rows = []
    closes = {"LONG": [100, 110, 121], "SHORT": [100, 90, 81]}
    for ticker, series in closes.items():
        for day, close in enumerate(series, start=2):
            rows.append(
                {
                    "date": pd.Timestamp(f"2024-01-0{day}"),
                    "ticker": ticker,
                    "close": close,
                    "available_at": f"2024-01-0{day}T21:00:00+00:00",
                }
            )
    return pd.DataFrame(rows)


def _factors() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2024-01-02"),
                pd.Timestamp("2024-01-02"),
                pd.Timestamp("2024-01-03"),
                pd.Timestamp("2024-01-03"),
            ],
            "ticker": ["LONG", "SHORT", "LONG", "SHORT"],
            "score": [1.0, -1.0, 1.0, -1.0],
            "available_at": [
                "2024-01-02T20:00:00+00:00",
                "2024-01-02T20:00:00+00:00",
                "2024-01-03T20:00:00+00:00",
                "2024-01-03T20:00:00+00:00",
            ],
        }
    )


def test_backtest_reports_costs_and_rank_ic() -> None:
    result = backtest_long_short(
        _prices(),
        _factors(),
        as_of_time=datetime(2024, 1, 4, 21, tzinfo=UTC),
        transaction_cost_bps=10,
    )

    assert result.report.periods == 2
    assert result.report.mean_rank_ic == pytest.approx(1.0)
    assert result.report.net_return < result.report.gross_return
    assert result.daily_results["turnover"].iloc[0] == pytest.approx(1.0)


def test_backtest_rejects_future_available_price() -> None:
    prices = _prices()
    prices.loc[0, "available_at"] = "2024-01-05T21:00:00+00:00"

    with pytest.raises(PointInTimeViolation):
        backtest_long_short(
            prices,
            _factors(),
            as_of_time=datetime(2024, 1, 4, 21, tzinfo=UTC),
        )
