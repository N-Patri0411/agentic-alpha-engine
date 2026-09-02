# 0003 — Agent-managed living graph

## Decision

Maintain the semiconductor graph as append-only immutable snapshots. Source
adapters write only `EvidenceObservation` records; they cannot modify edges.
The bounded Graph Adjudicator Agent clusters eligible observations, resolves
known aliases, and returns one typed decision for each entity-pair cluster.
`GraphPublisher` is the only component permitted to write a new snapshot.

The agent may approve a new edge, update its state, retire it, hold it, or
reject it. Edge changes are not free-form model numbers: each suggested state
change is multiplied by source-tier reliability and freshness decay, then
clipped to a maximum move of 0.20 per run. A single discovery-tier source
cannot add an edge; it needs two distinct sources or stronger primary/official
evidence. Invalid entities, unavailable evidence, unsupported observation IDs,
and missing support cause the decision to fail or hold.

## Consequences

- Prior graph snapshots are never rewritten; the scorer selects a snapshot by
  as-of time and never writes graph data.
- Event-driven source intake can create evidence at any time. A scheduler will
  consolidate it into a nightly snapshot in a later runtime slice.
- The model can interpret evidence but cannot call arbitrary web tools, files,
  or publishing code. Its output is validated before the deterministic policy
  and publisher apply it.
- The system records every state change as a scenario assumption. It does not
  claim a relationship or edge weight is economically predictive.
