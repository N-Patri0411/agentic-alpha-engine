# 0002 — Reviewed immutable graph snapshots

## Decision

Store supply-chain relationships in versioned JSON snapshots. Every edge must
reference canonical entity IDs, a source receipt, a validated extraction draft,
and an explicit governed approval decision. The snapshot includes a SHA-256 digest
of its edge payload and is write-once through `GraphPublisher`.

Scenario direction is always **upstream to downstream**: a disruption to the
upstream entity can propagate to its dependent. This is distinct from the
natural-language evidence direction. For example, NVIDIA stating that it uses
TSMC becomes the scenario edge `TSM -> NVDA`.

## Consequences

- A model draft cannot directly change the graph. The constrained Graph
  Adjudicator and deterministic publisher may do so only under their separate
  evidence and bounded-update policy.
- Edge state changes record their evidence and governed decision. They are
  bounded documented scenario assumptions, not unbounded LLM-supplied numbers.
- Corrections create a new snapshot version; existing snapshot files are never
  overwritten.
- The deterministic `RippleRiskScorer` consumes snapshots and exposes source
  paths, but makes no return or trading prediction.
