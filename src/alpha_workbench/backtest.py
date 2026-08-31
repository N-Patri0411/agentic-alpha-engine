"""Small, explicit paper backtest primitives for cross-sectional factors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .data import assert_available_as_of
from .models import BacktestReport


@dataclass(frozen=True)
class BacktestResult:
    """The audit table and summary report produced by one deterministic backtest."""

    daily_results: pd.DataFrame
    report: BacktestReport


def _annualized_sharpe(returns: pd.Series) -> float | None:
    if len(returns) < 2:
        return None
    deviation = float(returns.std(ddof=1))
    if np.isclose(deviation, 0):
        return None
    return float(np.sqrt(252) * returns.mean() / deviation)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    drawdowns = equity / equity.cummax() - 1
    return float(drawdowns.min())


def backtest_long_short(
    prices: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    as_of_time: datetime,
    tickers_per_side: int = 1,
    transaction_cost_bps: float = 5.0,
    trial_count: int = 1,
) -> BacktestResult:
    """Evaluate daily top/bottom factor ranks with an explicit paper cost model.

    Prices must contain close observations for the signal date and following date.
    The implementation is intentionally small and transparent; it is not an
    execution simulator or an investability claim.
    """

    if tickers_per_side < 1:
        raise ValueError("tickers_per_side must be at least one")
    if transaction_cost_bps < 0:
        raise ValueError("transaction_cost_bps cannot be negative")
    if trial_count < 1:
        raise ValueError("trial_count must be at least one")

    price_frame = prices.copy().sort_values(["ticker", "date"])
    factor_frame = factors.copy().sort_values(["date", "ticker"])
    required_prices = {"date", "ticker", "close"}
    required_factors = {"date", "ticker", "score"}
    if missing := required_prices.difference(price_frame.columns):
        raise ValueError(f"prices are missing columns: {sorted(missing)}")
    if missing := required_factors.difference(factor_frame.columns):
        raise ValueError(f"factors are missing columns: {sorted(missing)}")
    assert_available_as_of(price_frame, as_of_time)
    assert_available_as_of(factor_frame, as_of_time)

    price_frame["next_close"] = price_frame.groupby("ticker", sort=False)["close"].shift(-1)
    price_frame["forward_return"] = price_frame["next_close"] / price_frame["close"] - 1
    joined = factor_frame.merge(
        price_frame[["date", "ticker", "forward_return"]],
        on=["date", "ticker"],
        how="inner",
        validate="one_to_one",
    ).dropna(subset=["forward_return"])
    if joined.empty:
        raise ValueError("no factor observations have a next-period return")

    rows: list[dict[str, float | int | pd.Timestamp]] = []
    prior_weights: pd.Series = pd.Series(dtype=float)
    cost_rate = transaction_cost_bps / 10_000
    for date, group in joined.groupby("date", sort=True):
        ranked = group.sort_values(["score", "ticker"], ascending=[False, True]).reset_index(
            drop=True
        )
        if len(ranked) < 2 * tickers_per_side:
            continue
        longs = ranked.head(tickers_per_side).set_index("ticker")
        shorts = ranked.tail(tickers_per_side).set_index("ticker")
        weights = pd.concat(
            [
                pd.Series(0.5 / tickers_per_side, index=longs.index),
                pd.Series(-0.5 / tickers_per_side, index=shorts.index),
            ]
        )
        current_weights = weights.groupby(level=0).sum()
        union = current_weights.index.union(prior_weights.index)
        turnover = float(
            (
                current_weights.reindex(union, fill_value=0)
                - prior_weights.reindex(union, fill_value=0)
            )
            .abs()
            .sum()
        )
        selected = pd.concat([longs, shorts])
        gross_return = float(
            (current_weights * selected["forward_return"].reindex(current_weights.index)).sum()
        )
        net_return = gross_return - turnover * cost_rate
        rank_ic = float(
            group["score"]
            .rank(method="average")
            .corr(group["forward_return"].rank(method="average"))
        )
        rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "net_return": net_return,
                "turnover": turnover,
                "rank_ic": rank_ic,
                "long_count": tickers_per_side,
                "short_count": tickers_per_side,
            }
        )
        prior_weights = current_weights

    daily_results = pd.DataFrame(rows)
    if daily_results.empty:
        raise ValueError("no date has enough symbols for the requested long/short construction")
    net_returns = daily_results["net_return"]
    report = BacktestReport(
        as_of_time=as_of_time,
        periods=len(daily_results),
        mean_rank_ic=_finite_or_none(daily_results["rank_ic"].mean()),
        gross_return=float(daily_results["gross_return"].sum()),
        net_return=float(net_returns.sum()),
        annualized_sharpe=_annualized_sharpe(net_returns),
        max_drawdown=_max_drawdown(net_returns),
        average_turnover=float(daily_results["turnover"].mean()),
        transaction_cost_bps=transaction_cost_bps,
        trial_count=trial_count,
        limitations=[
            "Paper-only equal-weight construction; no borrow, margin, market-impact, "
            "or execution simulation.",
            "Metrics are research diagnostics and do not establish economic validity "
            "or future performance.",
        ],
    )
    return BacktestResult(daily_results=daily_results, report=report)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None
