# Project State

## Current milestone

Evidence-first source layer and bounded living-graph foundation.

## Verified capabilities

- The codebase defines durable research contracts and rejects observations that become available after a requested as-of time.
- A frozen CSV provider supports deterministic, offline backtest fixtures.
- The initial backtest creates equal-weight long/short paper positions, accounts for turnover costs, and reports rank IC, net returns, drawdown, and turnover.
- The scenario engine propagates a severity shock over effective-dated supply-chain edges and returns source-backed explanation paths.
- A reviewed semiconductor entity registry resolves CIKs, aliases, and whether
  an entity is tradeable. It now contains a 10-company core, including ASML and
  Applied Materials with configured SEC and official-IR source entries.
- The first immutable SEC-backed graph snapshot contains reviewed TSM-to-NVIDIA
  and TSM-to-AMD manufacturing dependencies. `RippleRiskScorer` replays it
  with evidence paths and rejects a tampered snapshot.
- Every future source can emit the same immutable `EvidenceObservation` envelope,
  with typed text, filing-fact, market-bar, or event-signal payloads. A local
  DuckDB ledger records observations, source-catalog entries, and run receipts
  append-only with idempotency protection.
- SEC multi-form, official investor-relations, official earnings, discovery, and
  Alpha Vantage daily-OHLCV adapters all emit that same observation envelope.
  Their normal test runs use frozen fixtures and need neither network nor keys.
- The bounded `collect-initial-sources` command now runs the initial
  semiconductor source matrix end-to-end into the ignored local DuckDB ledger:
  SEC filings and 8-K/6-K earnings exhibits for US/SEC filers, ten official
  investor-relations/newsroom entries plus bounded same-site release links,
  Tavily discovery results, and Alpha Vantage daily bars for eight tradeable
  entities. It records a receipt for every attempted adapter call rather than
  hiding failures.
- A real source smoke run confirmed live SEC, Tavily, and Alpha Vantage paths;
  the tracked research receipt documents the source-specific outcomes and known
  official-newsroom access failures rather than implying uniform coverage.
- The Extraction Agent now accepts common text observations, rather than only
  SEC-specific requests. It produces the same constrained relationship drafts
  after source collection has preserved the original evidence.
- The Graph Adjudicator resolves registered aliases, clusters source evidence,
  validates model output, and applies bounded reliability/freshness-weighted
  changes before the write-once publisher creates a new graph snapshot. One weak
  discovery source cannot add a graph edge.
- `EvidenceIntakeService` invokes only explicitly registered source adapters and
  writes a completed or failed collection receipt. `NightlyGraphConsolidator`
  reads ledger observations at a declared as-of time and routes them through the
  adjudicator to a write-once snapshot path.
- The first durable A2A workflow is live: an Extraction command produces a
  provenance-validated Graph Adjudicator review message, which returns an
  immutable-snapshot receipt to the Orchestrator. Duplicate deliveries are
  rejected through message idempotency keys.
- Historical scenario replay now selects only a graph snapshot available at the
  requested event time, rejects future-dated event evidence, and writes a
  non-overwritable scenario-run receipt. A typed graph-view export provides
  node risk severity and edge state for the future React/Cytoscape UI.
- A bounded live A2A trial successfully ran Luna for both Extraction and Graph
  Adjudication on current public NVIDIA and AMD 10-K passages. Its scratch
  snapshots are ignored local artifacts; no unreviewed output was promoted.
- Controlled post-discovery page retrieval now fetches actual readable content
  from reviewed official hosts, retains exact relationship-ranked passages, and
  passes them to Luna rather than treating titles and URLs as evidence. A live
  NVIDIA Newsroom trial produced an ignored `Hynix -> NVDA` graph-edge proposal
  through Extraction and Graph Adjudication; it was not promoted to the tracked
  reviewed graph.
- Beginner-friendly explanations are tracked under `docs/reference/` for both laptops.
- A local NetworkX-based HTML visualizer renders every registry entity, approved
  directed edge, relationship type, strength, confidence, and evidence link.
  It can render either a tracked reviewed snapshot or an ignored local trial.

## Next slices

1. Add an incremental evidence watermark so graph workflows process only new or
   changed observations, while keeping a full replay option for research.
2. Package the bounded extraction-to-adjudication path as a manual CLI, then
   add source-tier promotion and a review screen before scheduled publication.
3. Add snapshot-diff and event-timeline endpoints, then implement the first
   React/Cytoscape scenario explorer.
4. Build the ripple-to-factor bridge and use historical scenario-run receipts
   as versioned inputs to an honest backtest.
5. Add a small scheduler/CLI wrapper around the bounded intake and nightly
   consolidation services; it must remain manual-started in development.
6. Add reviewed official RSS/feed or documented-download fallbacks for the
   remaining Micron, GlobalFoundries, and UMC newsroom access failures; do not
   evade site access controls.
7. Add persistent source watermarks so repeated collection selects only new
   filings, releases, and bars rather than relying solely on ledger idempotency.
8. Extend evidence conflict/outlier clustering, then replay static and evolving
   snapshots across documented semiconductor events without future leakage.
9. Only after those baselines exist, resume feature/alpha-generation work.

## Known risks

- No production market-data provider is configured; demo CSVs are strictly illustrative.
- The scenario graph is deterministic at scoring time. Its graph-maintenance
  policy is new and has not yet been evaluated over a historical event replay.
- Backtest statistics are minimal initial diagnostics and do not establish investability.
- Local Codex plugin configuration does not synchronize; install it on both laptops. The tracked `AGENTS.md` carries the repository rules.
- React dependencies cannot be verified on this laptop until Node.js LTS is installed.
- Cloud LLM calls require a locally configured provider key; normal tests use a fake model.
- A complete real-source run additionally needs local Alpha Vantage and Tavily
  keys. The SEC, official-IR, and public SEC-earnings paths require no key.
- The tracked $2/day budget is a policy default; its persistent enforcement ledger is the next agent-runtime safety slice.
- Filing passage selection is keyword-based and is deliberately conservative. It now excludes
  hidden Inline-XBRL metadata, but it still needs broader section-aware ranking before large-scale
  research collection.

## Latest verification

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .test-tmp
.venv\Scripts\ruff.exe check .
.venv\Scripts\mypy.exe src
.venv\Scripts\python.exe -m alpha_workbench ripple-score --snapshot data/graph_snapshots/semiconductor-sec-reviewed-v1.json --shock TSM --severity 0.9 --as-of 2026-05-01T00:00:00+00:00
.venv\Scripts\python.exe -m alpha_workbench collect-initial-sources --preview-limit 32
.venv\Scripts\python.exe -m alpha_workbench visualize-graph --snapshot data/graph_snapshots/semiconductor-sec-reviewed-v1.json --output reports/semiconductor-graph.html
python -m alpha_workbench backtest --prices data/demo_prices.csv --factors data/demo_factors.csv --as-of 2024-01-05T21:00:00+00:00
python -m alpha_workbench scenario --edges data/semiconductor_edges.json --shock TSM --severity 0.9 --as-of 2024-01-15T00:00:00+00:00
scripts\setup.ps1
scripts\run-demos.ps1
```

The current suite has 80 passing tests with the command above. Replayable
synthetic demo output is recorded in `docs/reference/demo-results.md`. A live
NVIDIA 10-K and AMD 10-K produced draft, provenance-validated manufacturing
dependencies on TSM; a TSMC 20-F correctly produced no proposal when no
approved counterparty was named. The original two dependencies are in
`data/graph_snapshots/semiconductor-sec-reviewed-v1.json`; new snapshots are
write-once and use the bounded Graph Adjudicator policy. See
`docs/research/2026-09-01-live-sec-extraction-trial.md` and
`docs/decisions/0003-agent-managed-living-graph.md`. The full-page evidence and
Luna graph trial is recorded in
`docs/research/2026-09-02-web-content-and-luna-graph-trial.md`.
