# Historical validation and automation plan — 2026-09-30

## Objective

Turn the current manual research demonstration into a repeatable research
system that can test a graph-derived factor honestly over historical periods,
then run its approved workflow automatically with bounded orchestration and
signal-health monitoring. This work can produce evidence **for or against** a
hypothesis; it cannot promise or "prove" a profitable alpha in advance.

## Non-negotiable research boundary

An alpha claim needs a sufficiently long, point-in-time historical panel,
predeclared validation rules, comparison with simple baselines, costs, and
unseen periods. Free daily price downloads can power engineering development,
but do not establish a production-quality point-in-time research dataset.

## Workstreams

| Workstream | First deliverable | Acceptance test |
| --- | --- | --- |
| Historical graph-price panel | Immutable graph/price join, static-versus-evolving graph label, source hashes, and availability checks | A fixture proves each factor date uses only a snapshot and bars already available then; a later snapshot cannot alter an earlier row |
| Historical data acquisition | Provider-neutral backfill interface, acquisition manifest, data-quality report, and local cache policy | A deliberately incomplete or non-point-in-time provider is labelled and rejected for a research claim |
| Honest evaluation | Rolling walk-forward splits, purge/embargo where labels overlap, baseline comparison, trial accounting, costs, exposures | Future labels/data cannot reach a train split; a candidate has one locked final report |
| Automated Orchestrator | Typed state machine around approved standalone agents, persistent event ledger, bounded routing | Invalid transitions, repeated inputs, budget exhaustion, and non-retryable errors stop safely |
| Monitor | Deterministic health calculation and review events | Decay/staleness produces a Gatekeeper review event; it never silently retires or replaces a signal |
| Review and operations | Run dashboard/API endpoints, pause/resume, audit receipts, scheduled invocation only after manual acceptance | A stopped run resumes from its event state without duplicating an idempotent action |

## Delivery order

1. **Freeze the historical-panel contract.** Each panel row needs the factor
   date, graph snapshot ID/hash/availability, price observation IDs and their
   availability, universe, feature version, and an evolving/static label.
2. **Implement the panel builder using frozen fixtures.** It must select the
   most recent eligible graph snapshot at every date rather than retrofit the
   latest graph into history. This establishes the data shape before bulk
   downloads.
3. **Add acquisition manifests and a provider adapter.** Start with the
   existing Alpha Vantage development adapter. It can backfill prices for
   engineering but is explicitly marked unsuitable for a point-in-time alpha
   claim. Select a licensed provider before publishing research results.
4. **Upgrade evaluation.** Use rolling origin train/test windows, a locked final
   out-of-sample interval, realistic costs, trial counts, and static/price-only
   baselines. A poor result is preserved as a report, not tuned away.
5. **Implement Monitor before scheduling.** It computes rolling IC/returns,
   freshness, correlation, and drift from already accepted signals, then submits
   a typed Gatekeeper review event.
6. **Wire the bounded Orchestrator last.** It may route approved agent actions
   only. A deterministic policy enforces action allowlists, 12 steps, two
   retries, 20 LLM calls, a 15-minute cap, idempotency keys, and loop detection.
   LangGraph provides state routing/checkpoint integration; policy enforcement
   remains repository code.
7. **Run manual acceptance rehearsals, then schedule.** Scheduling comes only
   after a run receipt can show duration, retries, model/cost use, data hashes,
   decisions, and safe pause/resume behavior.

## Immediate data milestones

1. Create at least several dated semiconductor graph snapshots from evidence
   that was actually available on each historical date. Do not fabricate a
   graph history from today's knowledge.
2. Backfill enough subsequent daily prices for the tradable universe and retain
   provider retrieval/availability metadata. The minimum evaluation window will
   be configured rather than assumed.
3. Establish a coverage report: graph dates, source evidence by entity pair,
   missing nodes, price coverage, and reasons a row was excluded.
4. Compare three predefined baselines: price-only, static graph, and evolving
   graph. The evolving graph is useful only if it improves a locked evaluation
   without leakage.

## Architecture decisions

- The historical panel and Monitor are deterministic. Luna may propose a factor
  or route within an allowlist, but it cannot change measurements, data timing,
  gates, or portfolio safety rules.
- The Orchestrator is an agentic router wrapped around a deterministic policy
  engine. It has no shell, arbitrary URL, graph-publication, broker, or budget
  mutation capability.
- Monitor is advisory: it emits review events. Gatekeeper remains the only
  component allowed to decide whether a signal stays in the paper library.
- Keep raw data and provider credentials local/ignored. Track contracts,
  fixtures, manifests, hashes, test results, and research decisions in Git.

## Current implementation checkpoint

Luna subagents are implementing the independent historical-panel,
Orchestrator, and Monitor slices against frozen fixtures. They will be
integrated only after their contracts, tests, lint, and type checks pass.
