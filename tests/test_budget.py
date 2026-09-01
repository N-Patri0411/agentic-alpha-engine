from pathlib import Path

import pytest

from alpha_workbench.llm.budget import DailyBudgetLedger


def test_daily_ledger_blocks_reservations_beyond_limit(tmp_path: Path) -> None:
    ledger = DailyBudgetLedger(tmp_path / "budget.sqlite3", daily_limit_usd=0.20)
    ledger.reserve(0.10)
    ledger.reserve(0.10)
    with pytest.raises(RuntimeError, match="daily_budget_exhausted"):
        ledger.reserve(0.01)
