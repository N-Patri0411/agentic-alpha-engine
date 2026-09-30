# Alpha research workflow (current manual version)

## What the software is trying to do

A factor is a number assigned to a company on a date. The Alpha Generator
suggests a formula for turning available factors into a score. The backtester
asks whether repeatedly ranking companies by that score would have worked on
later historical prices **after estimated transaction costs**. The Gatekeeper
then accepts, rejects, or requests review using fixed rules. Only accepted
scores can become **paper** target weights; there is no broker connection.

Passing software tests means the calculation is reproducible. It does not mean
the factor predicts future prices.

## Current flow

```text
Evidence observations -> candidate graph (unapproved, for discovery)
                      -> reviewed graph snapshot -> deterministic ripple factor
Market bars --------------------------------------> dated prices

Factors + prices -> Alpha Generator (Luna or fake) -> restricted formula
                 -> deterministic evaluator -> cost-aware backtest + baseline
                 -> deterministic Gatekeeper -> paper targets only if accepted
```

Candidate evidence is **not** quietly fed into the ripple factor. Only a
reviewed, time-stamped snapshot is eligible. The source tier filter was lifted
for candidate discovery, but evidence quality still matters when a graph edge
is adjudicated.

## Try the hand-authored demo (no key or network)

```powershell
.venv\Scripts\python.exe -m alpha_workbench alpha-run `
  --prices data/demo_prices.csv `
  --features data/demo_factors.csv `
  --as-of 2024-01-05T21:00:00+00:00 `
  --run-id demo-alpha `
  --receipt reports/demo-alpha.json
```

The demo CSVs are **hand-authored test fixtures**. They are useful for checking
the code path, not for financial conclusions. `--llm configured` invokes the
model selected for `alpha_generator` in `config/models.yaml` and consumes a
small amount of API credit. The default `offline` mode uses a deterministic
fake model. Keep the provider key in the ignored root `.env`, never in Git.

## Try a reviewed graph with retained market bars

```powershell
.venv\Scripts\python.exe -m alpha_workbench alpha-run-graph `
  --snapshot data/graph_snapshots/semiconductor-sec-reviewed-v1.json `
  --ledger data/private/evidence.duckdb `
  --market-run-id alpha-vantage-daily `
  --shock TSM `
  --as-of 2026-09-30T21:00:00+00:00 `
  --receipt reports/graph-alpha.json
```

This reads the **local** ignored ledger; its bars do not synchronize between
laptops. The command filters observations by their actual availability time,
then checks that the graph snapshot was already available. The receipt records
the graph and market-observation identifiers. With the current retained data,
it rejects the run for insufficient post-snapshot history and produces no
paper weights. That is the expected honest result.

## What is still required before calling this an alpha

We need many dated, point-in-time graph snapshots and enough subsequently
available prices. Then we must compare a proposed graph factor with simple
price and static-graph baselines on rolling **unseen** periods, include trading
costs, track every formula attempted, test overlapping-label leakage, and
check exposures and stability. A short historical demo or one good formula
receipt is not proof of economic value.
