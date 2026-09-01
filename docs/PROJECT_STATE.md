# Project State

## Current milestone

Phase 2: SEC extraction and evidence review (passage-selection hardening).

## Verified capabilities

- The codebase defines durable research contracts and rejects observations that become available after a requested as-of time.
- A frozen CSV provider supports deterministic, offline backtest fixtures.
- The initial backtest creates equal-weight long/short paper positions, accounts for turnover costs, and reports rank IC, net returns, drawdown, and turnover.
- The scenario engine propagates a severity shock over effective-dated supply-chain edges and returns source-backed explanation paths.
- Beginner-friendly explanations are tracked under `docs/reference/` for both laptops.

## Next slices

1. Verify and push the Phase 0 architecture skeleton.
2. Install Node.js LTS on both laptops, then verify the React review-app shell.
3. Implement Phase 1: entity registry, typed graph snapshots, and `RippleRiskScorer`.
4. Implement Phase 2: SEC collection, evidence validation, and human-review inbox.

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
python -m alpha_workbench backtest --prices data/demo_prices.csv --factors data/demo_factors.csv --as-of 2024-01-05T21:00:00+00:00
python -m alpha_workbench scenario --edges data/semiconductor_edges.json --shock TSM --severity 0.9 --as-of 2024-01-15T00:00:00+00:00
scripts\setup.ps1
scripts\run-demos.ps1
```

The test suite currently contains nine passing tests. Replayable synthetic demo
output is recorded in `docs/reference/demo-results.md`.

The SEC extraction slice has 33 passing tests with the command above. A live
NVIDIA 10-K and AMD 10-K produced draft, provenance-validated manufacturing
dependencies on TSM; a TSMC 20-F correctly produced no proposal when no
approved counterparty was named. See `docs/research/2026-09-01-live-sec-extraction-trial.md`.
