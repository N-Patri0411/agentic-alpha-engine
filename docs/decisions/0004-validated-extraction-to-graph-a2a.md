# 0004 — Validated Extraction-to-Graph A2A hand-off

## Decision

Use the local DuckDB A2A bus for the first real agent hand-off:
`orchestrator -> extraction -> graph_adjudicator -> orchestrator`. The
Extraction Agent receives common evidence observations, proposes relationships,
and applies deterministic quote/entity validation. Only proposals with a
`pass` validation result, alongside their linked source observations, may appear
in the Graph Adjudicator's review message.

Every message has a trace ID, run ID, parent-ready envelope, typed payload,
and idempotency key. The local bus rejects duplicate idempotency keys even when
they arrive with a different message ID. The consumer acknowledges an input
only after it has successfully created its next message or graph result.

## Consequences

- The Graph Adjudicator no longer needs to receive an unfiltered stream of raw
  observations in this workflow.
- Source evidence remains immutable in the ledger; messages carry only the
  bounded records needed to progress a run.
- The flow is deliberately two transitions, not an open-ended agent loop.
  LangGraph orchestration remains deferred until each agent workflow is proven.
- A future queue transport can replace DuckDB while preserving the message and
  payload contracts.
