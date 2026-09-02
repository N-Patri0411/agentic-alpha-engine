# 0005 — Historical scenario replay is point-in-time and write-once

## Decision

Represent a historical shock as a typed `HistoricalEvent` with an observed
time, an availability time, an affected entity, a bounded severity assumption,
and source-observation references. Replaying the event selects the newest
immutable graph snapshot whose `created_at` is not later than the requested
as-of time. The replay records its selected snapshot hash and deterministic
`RippleRiskScorer` result in a write-once `HistoricalScenarioRun` JSON file.

The initial scope is one direct shock entity per event. This deliberately does
not claim that it models an entire market crash or establishes a trade signal.

## Consequences

- A replay fails rather than quietly using an event or snapshot from the future.
- The event, graph version, assumptions, and output can be inspected and
  reproduced later.
- The typed graph-view export exposes node severity and edge state for a future
  React/Cytoscape viewer without coupling research storage to a UI library.
- A later ripple-to-factor slice may use scenario-run receipts as versioned
  inputs, but must still test them against later realised prices.
