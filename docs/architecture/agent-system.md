# Agent System Architecture

## Purpose

The workbench is a paper-research system. It never sends broker orders or gives
investment instructions. Seven required agents work through a bounded, manual
workflow; the optional Research Agent is built last.

## Canonical roles

| Role | Responsibility | Current state |
| --- | --- | --- |
| Orchestrator | Bounded, LLM-assisted routing and run accounting | Policy checks, append-only run ledger, and injected-handler LangGraph wiring implemented; scheduled operation pending |
| Extraction | Convert sourced inputs into versioned feature observations | Multi-source evidence intake and relationship extraction implemented; broader feature extraction pending |
| Alpha Generator | Propose typed factor DSL expressions | Bounded model-backed generator and restricted DSL implemented |
| Backtester | Evaluate candidates with point-in-time data | Standalone agent, costs and baseline implemented; rolling walk-forward and full trial accounting pending |
| Gatekeeper | Apply acceptance/rejection policy | Deterministic first policy implemented; statistical controls pending |
| Portfolio Optimiser | Create paper-only targets | Bounded paper target construction implemented; richer exposure controls pending |
| Monitor | Measure realised quality/freshness/crowding and request Gatekeeper review | Deterministic health evaluator implemented; scheduling and production history pending |
| Research (optional) | Propose new data-source research | Skeleton |

This table describes the 2026-09-30 checkpoint. The manual `alpha-run` and
`alpha-run-graph` commands still call standalone agents in a fixed sequence.
The new bounded graph is an opt-in execution shell: callers inject the
standalone handlers and a model client, and the shell records each route and
pauses on unsafe or incomplete work. It is not a scheduler.

The semiconductor graph and eventual GNN are Extraction Agent tools, not extra
agents. Evidence collection and evidence validation are internal Extraction
workers. The bounded Graph Adjudicator is a graph-maintenance agent: it receives
only immutable evidence observations and may publish a reviewed snapshot through
the deterministic publisher. It is not part of the seven-agent alpha pipeline
and cannot trade, discover arbitrary tools, or bypass evidence rules. The
Gatekeeper decides research quality; it does not validate a filing quote.

## Orchestrator controls

- The agent can select only actions in the tracked allowlist.
- A run is limited to 12 steps, 20 model calls, two retries per action, and 15
  minutes by default.
- The same action with the same input hash is allowed twice; a third attempt
  marks the run `loop_detected`.
- Every proposed action has an idempotency key and run-ledger event.
- Budget exhaustion or an invalid response pauses the workflow for review.
- The Orchestrator cannot invoke shell commands, arbitrary URLs, graph
  publication, signal acceptance, or broker execution.
- LangGraph nodes receive only explicitly injected handler callables. A missing
  handler, malformed model response, unknown exception, or non-completed agent
  result pauses the run with an actionable reason.
- Retryable failures are retried only through the same named action and remain
  subject to the step, call, wall-clock, and repeated-action limits.
- `RunEventLedger` stores idempotency-keyed route events in DuckDB; it is
  separate from the append-only evidence ledger and does not mutate research
  inputs.

## Model boundary

All product agents receive an `LLMClient` from
`src/alpha_workbench/llm/models.py`. `config/models.yaml` chooses the provider
and model for each role; `.env` supplies credentials. Tests use `FakeLLMClient`
and never make network calls.

## Incremental delivery

1. Phase 0: architecture, contracts, model boundary, agent/API/UI skeletons.
2. Phase 1: evidence-backed semiconductor entities, graph snapshots, and
   `RippleRiskScorer`.
3. Phase 2: SEC collection, extraction/validation workers, and review inbox.
4. Phase 3: factor DSL, generator, and rigorous evaluator.
5. Phase 4: Gatekeeper and Monitor policies.
6. Phase 5: paper optimiser and bounded LangGraph wiring.

Each phase must be independently tested, demonstrated, committed, and pushed
before the next begins.
