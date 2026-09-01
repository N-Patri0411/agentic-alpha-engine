"""Conservative local reservation ledger for manually authorized cloud calls."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class DailyBudgetLedger:
    def __init__(self, path: Path, *, daily_limit_usd: float) -> None:
        self._path = path
        self._limit = daily_limit_usd
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "create table if not exists llm_reservations (day text, amount real not null)"
            )

    def reserve(self, amount_usd: float) -> None:
        if amount_usd <= 0:
            raise ValueError("reservation must be positive")
        day = datetime.now(UTC).date().isoformat()
        with sqlite3.connect(self._path) as connection:
            spent = connection.execute(
                "select coalesce(sum(amount), 0) from llm_reservations where day = ?", [day]
            ).fetchone()[0]
            if float(spent) + amount_usd > self._limit:
                raise RuntimeError("daily_budget_exhausted")
            connection.execute("insert into llm_reservations values (?, ?)", [day, amount_usd])
