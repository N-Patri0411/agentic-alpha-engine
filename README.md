# Agentic Alpha Research Workbench

An open-source, local-first workbench for reproducible quantitative research and paper portfolios. The project is intentionally evidence-first: a factor is a testable hypothesis with versioned inputs and an auditable report, not a trading instruction.

## What works now

- Typed research records for datasets, features, hypotheses, research runs, backtests, signal health, and scenarios.
- Frozen CSV market-data provider with point-in-time availability checks.
- Cost-aware, gross-normalized long/short factor backtest and JSON report.
- Effective-dated, sourced semiconductor supply-chain shock propagation.
- Point-in-time historical-event replay with immutable scenario-run receipts
  and graph-view export data for the upcoming React viewer.
- Fixture-based tests that run without network access.

## Quick start

Python 3.11 is required. Create a virtual environment, install the development dependencies, then run:

For the simplest Windows setup, double-click `setup.cmd`. It creates the local `.venv`, installs dependencies, and runs the full verification suite. Then double-click `run-demos.cmd` to run the offline examples.

```powershell
python -m alpha_workbench backtest --prices data/demo_prices.csv --factors data/demo_factors.csv --as-of 2024-01-05T21:00:00+00:00
python -m alpha_workbench scenario --edges data/semiconductor_edges.json --shock TSM --severity 0.9 --as-of 2024-01-15T00:00:00+00:00
pytest
```

If `python` is not available on a new Windows machine, install Python 3.11 first, then repeat the commands above from an activated virtual environment.

## Workflow

Before every shared work session, update `main` and read [PROJECT_STATE.md](docs/PROJECT_STATE.md). Commit and push every verified slice, including the relevant test and documentation update. See [AGENTS.md](AGENTS.md) for the full working agreement.

## Safety and scope

This is research and paper-portfolio software, not investment advice and not a live-trading system. Free market-data adapters are developer conveniences, not a production-data claim. The application never stores credentials in the repository.


