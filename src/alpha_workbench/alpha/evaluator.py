"""Safe evaluation of the restricted factor DSL over dated feature rows.

This module deliberately operates on pandas frames and the parsed DSL AST; it
never evaluates model text as Python.  Derived values use only observations at
or before the current row for each ticker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import numpy as np
import pandas as pd

from ..data import assert_available_as_of
from .dsl import Expression, parse_expression


def evaluate_factor_expression(
    features: pd.DataFrame,
    expression: str,
    *,
    feature_names: set[str] | list[str],
    as_of_time: datetime,
) -> pd.DataFrame:
    """Return ``date,ticker,score,available_at`` for one validated formula.

    Rolling operators require a complete lookback window.  Insufficient rows,
    missing values, and zero denominators become missing scores and are omitted
    before the backtest; no values are imputed or forward-filled.
    """

    required = {"date", "ticker", "available_at"}.union(feature_names)
    missing = required.difference(features.columns)
    if missing:
        raise ValueError(f"features are missing columns: {sorted(missing)}")
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    assert_available_as_of(frame, as_of_time)
    frame = frame.sort_values(["ticker", "date"]).reset_index(drop=True)
    ast = parse_expression(expression, feature_names)
    values = _evaluate(ast, frame, set(feature_names))
    result = frame[["date", "ticker", "available_at"]].copy()
    result["score"] = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=["score"]).sort_values(["date", "ticker"])
    if result.empty:
        raise ValueError("formula produced no finite scores")
    return result.reset_index(drop=True)


def _number(node: Expression) -> float:
    try:
        return float(node.name)
    except ValueError as exc:
        raise ValueError(f"expected a numeric DSL argument, got {node.name!r}") from exc


def _evaluate(node: Expression, frame: pd.DataFrame, names: set[str]) -> pd.Series:
    if not node.args:
        if node.name in names:
            return pd.to_numeric(frame[node.name], errors="coerce")
        return pd.Series(_number(node), index=frame.index, dtype=float)
    args = [
        _evaluate(arg, frame, names)
        if isinstance(arg, Expression) and arg.name in names | set(_FUNCTIONS)
        else (_number(arg) if isinstance(arg, Expression) else arg)
        for arg in node.args
    ]
    if node.name == "Rank":
        return _as_series(args[0], frame).groupby(frame["date"], sort=False).rank(pct=True)
    if node.name == "ZScore":
        source = _as_series(args[0], frame)
        grouped = source.groupby(frame["date"], sort=False)
        mean, std = grouped.transform("mean"), grouped.transform("std", ddof=0)
        return (source - mean).where(std > 0, 0.0) / std.where(std > 0, 1.0)
    if node.name in {"Add", "Sub", "Mul"}:
        left, right = (_as_series(value, frame) for value in args)
        return {"Add": left + right, "Sub": left - right, "Mul": left * right}[node.name]
    if node.name == "Div":
        left, right = (_as_series(value, frame) for value in args)
        return left / right.where(right != 0)
    if node.name == "Neg":
        return -_as_series(args[0], frame)
    if node.name in {"Delay", "Delta", "Mean", "StdDev"}:
        source, period_raw = args
        period = _period(period_raw)
        source = _as_series(source, frame)
        grouped = source.groupby(frame["ticker"], sort=False)
        if node.name == "Delay":
            return grouped.shift(period)
        if node.name == "Delta":
            return source - grouped.shift(period)
        rolling = grouped.rolling(period, min_periods=period)
        values = rolling.mean() if node.name == "Mean" else rolling.std(ddof=0)
        return values.reset_index(level=0, drop=True).reindex(frame.index)
    if node.name == "Correlation":
        left, right, period_raw = (_as_series(args[0], frame), _as_series(args[1], frame), args[2])
        period = _period(period_raw)
        work = pd.DataFrame({"left": left, "right": right, "ticker": frame["ticker"]})
        result = work.groupby("ticker", sort=False, group_keys=False).apply(
            lambda group: group["left"].rolling(period, min_periods=period).corr(group["right"]),
            include_groups=False,
        )
        return result.reset_index(level=0, drop=True).reindex(frame.index)
    if node.name == "Clip":
        return _as_series(args[0], frame).clip(
            lower=_scalar(args[1]), upper=_scalar(args[2])
        )
    raise ValueError(f"DSL function {node.name!r} is not implemented")


def _period(value: object) -> int:
    if isinstance(value, pd.Series):
        if value.empty:
            raise ValueError("lookback is empty")
        value = value.iloc[0]
    numeric = float(cast(Any, value))
    period = int(numeric)
    if period < 1 or numeric != period or period > 252:
        raise ValueError("lookback must be an integer between 1 and 252")
    return period


def _as_series(value: object, frame: pd.DataFrame) -> pd.Series:
    if isinstance(value, pd.Series):
        return value
    return pd.Series(float(cast(Any, value)), index=frame.index, dtype=float)


_FUNCTIONS = {
    "Rank", "ZScore", "Delay", "Delta", "Mean", "StdDev", "Correlation",
    "Add", "Sub", "Mul", "Div", "Neg", "Clip",
}


def _scalar(value: object) -> float:
    if isinstance(value, pd.Series):
        value = value.iloc[0]
    return float(cast(Any, value))
