# Project State

## Current milestone

Evidence-platform foundation: common immutable evidence records and local ledger.

## Verified capabilities

- The codebase defines durable research contracts and rejects observations that become available after a requested as-of time.
- A frozen CSV provider supports deterministic, offline backtest fixtures.
- The initial backtest creates equal-weight long/short paper positions, accounts for turnover costs, and reports rank IC, net returns, drawdown, and turnover.
- The scenario engine propagates a severity shock over effective-dated supply-chain edges and returns source-backed explanation paths.
- A reviewed semiconductor entity registry resolves CIKs, aliases, and whether
  an entity is tradeable.
- The first immutable SEC-backed graph snapshot contains reviewed TSM-to-NVIDIA
  and TSM-to-AMD manufacturing dependencies. `RippleRiskScorer` replays it
  with evidence paths and rejects a tampered snapshot.
- Every future source can emit the same immutable `EvidenceObservation` envelope,
  with typed text, filing-fact, market-bar, or event-signal payloads. A local
  DuckDB ledger records observations, source-catalog entries, and run receipts
  append-only with idempotency protection.
- Beginner-friendly explanations are tracked under `docs/reference/` for both laptops.

## Next slices

1. Implement SEC multi-form and official investor-relations adapters against the common evidence contract.
2. Implement official earnings evidence, web discovery/corroboration, and market-data adapters.
3. Refactor the Extraction Agent to collect common observations before proposing graph evidence.
4. Build Graph Adjudicator policy and temporal state after source coverage is proven.

## Known risks

- No production market-data provider is configured; demo CSVs are strictly illustrative.
- The scenario graph is deterministic and hand-curated. It is not a trained predictive model.
- Backtest statistics are minimal initial diagnostics and do not establish investability.
- Local Codex plugin configuration does not synchronize; install it on both laptops. The tracked `AGENTS.md` carries the repository rules.
- React dependencies cannot be verified on this laptop until Node.js LTS is installed.
- Cloud LLM calls require a locally configured provider key; normal tests use a fake model.
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
python -m alpha_workbench backtest --prices data/demo_prices.csv --factors data/demo_factors.csv --as-of 2024-01-05T21:00:00+00:00
python -m alpha_workbench scenario --edges data/semiconductor_edges.json --shock TSM --severity 0.9 --as-of 2024-01-15T00:00:00+00:00
scripts\setup.ps1
scripts\run-demos.ps1
```

The test suite currently contains nine passing tests. Replayable synthetic demo
output is recorded in `docs/reference/demo-results.md`.

The evidence-platform and SEC extraction slices have 39 passing tests with the command above. A live
NVIDIA 10-K and AMD 10-K produced draft, provenance-validated manufacturing
dependencies on TSM; a TSMC 20-F correctly produced no proposal when no
approved counterparty was named. The two approved dependencies are now in
`data/graph_snapshots/semiconductor-sec-reviewed-v1.json`. See
`docs/research/2026-09-01-live-sec-extraction-trial.md`.
