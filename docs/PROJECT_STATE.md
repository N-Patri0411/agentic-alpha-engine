# Project State

## Current milestone

Sprint 1: credible single-factor research lab.

## Verified capabilities

- The codebase defines durable research contracts and rejects observations that become available after a requested as-of time.
- A frozen CSV provider supports deterministic, offline backtest fixtures.
- The initial backtest creates equal-weight long/short paper positions, accounts for turnover costs, and reports rank IC, net returns, drawdown, and turnover.
- The scenario engine propagates a severity shock over effective-dated supply-chain edges and returns source-backed explanation paths.

## Next slices

1. Install Python 3.11 and project dependencies on each laptop, then run the test suite.
2. Add an SEC EDGAR client with user-agent configuration, rate limiting, caching, and frozen response fixtures.
3. Add walk-forward split generation and a research-run persistence layer in DuckDB.

## Known risks

- No production market-data provider is configured; demo CSVs are strictly illustrative.
- The scenario graph is deterministic and hand-curated. It is not a trained predictive model.
- Backtest statistics are minimal initial diagnostics and do not establish investability.
- Local Codex plugin configuration does not synchronize; install it on both laptops. The tracked `AGENTS.md` carries the repository rules.

## Latest verification

```powershell
python -m pytest
python -m alpha_workbench backtest --prices data/demo_prices.csv --factors data/demo_factors.csv --as-of 2024-01-05T21:00:00+00:00
python -m alpha_workbench scenario --edges data/semiconductor_edges.json --shock TSM --severity 0.9 --as-of 2024-01-15T00:00:00+00:00
```
