# Reviewed-graph plus market-data alpha trial — 2026-09-30

## Inputs and run

The offline manual pipeline used the tracked reviewed snapshot
`data/graph_snapshots/semiconductor-sec-reviewed-v1.json` and market-bar
observations already stored under run ID `alpha-vantage-daily` in the ignored
local DuckDB evidence ledger. It applied a TSM shock as of
`2026-09-30T21:00:00+00:00`. This trial did not call an LLM, fetch new data, or
spend API credit.

```powershell
.venv\Scripts\python.exe -m alpha_workbench alpha-run-graph `
  --snapshot data/graph_snapshots/semiconductor-sec-reviewed-v1.json `
  --ledger data/private/evidence.duckdb `
  --market-run-id alpha-vantage-daily `
  --shock TSM `
  --as-of 2026-09-30T21:00:00+00:00 `
  --receipt reports/offline-graph-alpha-receipt-v2.json
```

## Outcome

The graph feature path produced six dated entity rows, with market-observation
IDs and the graph snapshot hash recorded in the local receipt. The receipt's
SHA-256 is
`3be9e3b6373e5bf85b2ea4a1e8effe6bf4ac7ea1f0cae7debd770e97d65cf977`.

Only two usable post-snapshot market dates remained. A next-period return
series could not be formed, so the command returned a typed `rejected`
decision and no paper targets. It did not make up returns to complete the
backtest. A regression test now checks that a same-day market bar published
**after** a snapshot's availability is retained; filtering by the bar's
midnight trading-date label had incorrectly excluded it in the first run.

## Interpretation

This proves that reviewed graph state and retained real market observations can
enter the same provenance-aware research command. It does not prove predictive
power. The next real-data validation requires a much longer historical graph
series and subsequent market bars, plus rolling out-of-sample comparison with
simple baselines.
