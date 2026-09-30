# Alpha pipeline acceleration — 2026-09-30

## Objective

Make one manual, reproducible research run connect collected evidence, a
versioned graph, a graph-derived feature, a generated factor candidate, an
honest backtest, a deterministic acceptance decision, and paper-only output.
The first run is a software integration demonstration. It cannot establish
that an alpha exists.

## Decisions for this build

- Candidate graph discovery may consider text observations from every
  configured source tier. Keep source kind, tier, URL, time, exact content or
  summary status, and extraction provenance in each candidate record.
- Market bars may be used as numeric features. A bar alone does not establish
  a named commercial relationship.
- Keep candidate discovery separate from reviewed scenario topology; make the
  distinction visible in output. Do not fill missing nodes with invented edges.
- Use small, bounded manual runs and the existing $2/day local LLM guard.
- Keep every research run paper-only and preserve point-in-time checks.

## Work packages

| Package | Starting state | Completion check |
| --- | --- | --- |
| Broad candidate discovery | Official/primary text filter remains | All text source tiers can enter; provenance is visible; non-text data stays typed |
| Graph semantics | Scenario engine works on reviewed snapshots | Competitive, customer, and collaboration candidates are represented without implying supply-shock propagation |
| Graph-derived feature | RippleRiskScorer works separately | A versioned scenario result becomes date/entity factor rows with availability checks |
| Alpha Generator | Agent skeleton | Injected-model callable returns valid, bounded typed DSL candidates |
| Backtester Agent | Engine exists; agent skeleton | Candidate formula and frozen factor/price inputs produce an immutable report and simple baseline comparison |
| Gatekeeper | Agent skeleton | Deterministic policy gives typed accept/reject/review reasons; no direct promotion |
| Paper use | Portfolio agent skeleton | Accepted candidate can create paper target weights, with no broker path |
| Manual orchestration | Separate commands | One reproducible CLI/run receipt links input hashes, graph version, formula, test split, report, decision, and paper output |
| Reliability | Partial offline tests | Source provenance, timing leakage, malformed formula, costs, determinism, and negative-result tests pass |

## Order of integration

1. Merge broad candidate discovery, formula generation, and graph/backtest
   bridge interfaces from isolated coding packages.
2. Run source and model-free tests. Repair contract mismatches before adding
   orchestration.
3. Implement Gatekeeper and paper-only usage after a reproducible report exists.
4. Add a manual end-to-end command and a local demonstration receipt.
5. Update `PROJECT_STATE.md`, commit, and push each verified slice to `main`.

## What is out of scope for the first integrated run

Autonomous scheduled trading, a claim of profitable alpha, broker execution,
and a production-grade historical market-data license. Those require separate
evidence, evaluation, and operational work.

## Completion checkpoint — 2026-09-30

- The source filter was broadened for candidate discovery and graph-build
  selection. Text from every configured source tier can be considered; the
  source tier and whether the evidence is a discovery summary remain visible.
  Market bars are still typed numeric observations, not relationship claims.
- The restricted formula DSL, Luna-backed Alpha Generator, graph-derived
  factor bridge, Backtester Agent, Gatekeeper, paper-only target builder, and
  two manual alpha commands are implemented. Offline tests cover a successful
  paper-output branch as well as rejected, malformed, and insufficient-data
  branches.
- A configured Luna run generated `Rank(score)` from the hand-authored demo
  feature file. It was correctly rejected after a three-period backtest.
- A reviewed-graph plus retained Alpha Vantage run created six graph-factor
  rows. It was rejected because the post-snapshot price history cannot supply
  a meaningful next-period return series. Neither rejection is a failed
  software run; both are honest scientific outcomes.
- The next research milestone is not another agent skeleton. It is sufficient
  pair-specific evidence and a historical, point-in-time graph/price panel for
  rolling out-of-sample comparison with simple baselines. See `PROJECT_STATE.md`.
