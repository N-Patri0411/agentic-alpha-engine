from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alpha_workbench.llm.budget import DailyBudgetLedger


def test_daily_ledger_blocks_reservations_beyond_limit(tmp_path: Path) -> None:
    ledger = DailyBudgetLedger(tmp_path / "budget.sqlite3", daily_limit_usd=0.20)
    ledger.reserve(0.10)
    ledger.reserve(0.10)
    with pytest.raises(RuntimeError, match="daily_budget_exhausted"):
        ledger.reserve(0.01)


def test_daily_ledger_serializes_concurrent_reservations(tmp_path: Path) -> None:
    ledger = DailyBudgetLedger(tmp_path / "concurrent-budget.sqlite3", daily_limit_usd=0.10)

    def reserve() -> bool:
        try:
            ledger.reserve(0.06)
        except RuntimeError as error:
            assert str(error) == "daily_budget_exhausted"
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda _index: reserve(), range(8)))

    assert accepted.count(True) == 1
