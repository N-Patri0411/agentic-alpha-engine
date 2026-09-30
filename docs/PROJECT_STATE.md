# Project State

## Current milestone

Manual evidence-to-graph-to-alpha research path integrated (2026-09-30). This is
a working software path, not evidence of a profitable alpha or a complete
semiconductor relationship graph.

## What works now

- SEC, official investor-relations/earnings, Tavily discovery, and Alpha Vantage
  daily-bar adapters write typed, time-stamped observations to an append-only
  local DuckDB ledger. Ordinary tests use frozen fixtures and need no keys.
- Extraction and Graph Adjudication communicate through typed A2A messages.
  Reviewed graph snapshots are immutable JSON. The initial tracked snapshot
  contains two TSM manufacturing dependencies; local trials can contain more.
- Candidate discovery can examine **all text source tiers**, including discovery
  summaries, without pretending they are all equally reliable. It retains
  source provenance and can display first-hop entities outside the ten-company
  core. Numeric market bars remain numeric observations, not relationship text.
- Relationship types that do not imply a supply shock, such as competition or
  collaboration, can be displayed without being propagated by the deterministic
  ripple scorer. A candidate edge is not automatically a reviewed graph edge.
- The Alpha Generator is a standalone typed agent. It uses the injected model
  boundary (configured Luna or offline fake), validates formulas against a
  restricted feature DSL, and records rejected model outputs.
- Graph ripple scores can become dated factor rows with graph-snapshot and
  market-bar provenance. The Backtester Agent evaluates candidate and baseline
  returns with costs; a chronological holdout is created when enough dates
  exist. The deterministic Gatekeeper can reject, request review, or accept.
  Only an accepted candidate can produce paper target weights. There is no
  broker or live-order path.
- `alpha-run` runs the manual generator-to-paper research path from CSVs.
  `alpha-run-graph` starts from a reviewed graph snapshot and local market-bar
  observations. Both write reproducibility receipts. Candidate discovery has
  its own JSON and HTML visualizer, separate from the reviewed-graph view.

## Latest actual runs

- A bounded Luna candidate-discovery run on eight official text observations
  produced seven **unapproved candidate** relationships around the ten anchors.
  A broader official-plus-discovery selection produced one candidate. Different
  selected evidence yields different coverage; neither run proves a fully
  connected ten-company graph. Details: `docs/research/2026-09-30-candidate-live-trials.md`.
- A configured Luna `alpha-run` proposed `Rank(score)` against hand-authored
  demo CSVs. The run completed and Gatekeeper rejected it because it had only
  three backtest periods and no out-of-sample evidence. This validates the
  software flow, not the formula's financial value. Details:
  `docs/research/2026-09-30-alpha-generator-live-trial.md`.
- An offline `alpha-run-graph` used the reviewed TSM graph and retained Alpha
  Vantage bars. Six graph-factor rows were scored. It was rejected for too
  little post-snapshot price history; no return or paper weights were invented.
  Local receipt: `reports/offline-graph-alpha-receipt-v2.json` (ignored by Git).

## Next slices, in order

1. Collect and preserve more pair-specific source content for all ten core
   companies, including competitor, customer, equipment, and foundry links.
   Measure evidence coverage by pair and relationship type. Do not invent
   edges merely to connect isolated nodes.
2. Build a date-indexed, immutable **historical** graph series and acquire
   adequate licensed/usable price history after each graph's availability.
   The current real-source ledger is too short for an honest validation run.
3. Upgrade the alpha evaluator from one chronological holdout to rolling
   walk-forward tests with purging/embargo where labels overlap, exposure
   reporting, trial accounting, and false-discovery controls. Compare graph
   factors against simple price and static-graph baselines.
4. Add graph snapshot diffs and event-timeline inspection, then wire the
   review/alpha receipts into the React UI.
5. Implement incremental source watermarks, source-access fallbacks, Monitor,
   and the bounded LangGraph Orchestrator. Keep development runs manual and
   paper-only until those components are verified.

## Known risks and boundaries

- Allowing every text tier into **candidate discovery** improves recall, not
  factual certainty. Discovery summaries may omit context; provenance and
  weaker reliability remain visible. Graph publication still requires the
  adjudication policy. The locally viewed candidate graph is not a trading
  input.
- There are too few retained post-snapshot daily bars to backtest the real
  graph-derived factor. The demo CSVs are hand-authored fixtures.
- The Gatekeeper is a conservative first software policy, not a complete
  statistical proof. The current holdout is not full walk-forward validation.
- Free Alpha Vantage data is development-only and not a production-grade
  point-in-time dataset. Source licenses and website access controls matter.
- Keys and private ledgers remain only in ignored local files. All durable
  project decisions, code, tests, and handoffs belong in Git so both laptops
  stay synchronized. Both laptops must configure provider secrets locally.

## Latest verification

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
.venv\Scripts\python.exe -m alpha_workbench alpha-run --help
.venv\Scripts\python.exe -m alpha_workbench alpha-run-graph --help
.venv\Scripts\python.exe -m alpha_workbench discover-candidate-graph --help
```

At this checkpoint the suite has 117 passing tests; lint and type checks pass.
See `docs/plans/2026-09-30-alpha-pipeline-acceleration.md` and
`docs/reference/alpha-research-workflow.md` for the development map and usage.
