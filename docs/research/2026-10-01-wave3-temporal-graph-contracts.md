# Wave 3 Temporal Graph Contracts and Storage

## Contract boundary

Graph v2 stores complete immutable snapshots under
`alpha_workbench.temporal_graph`. A snapshot pins its workspace, locked universe,
complete instrument node-ID membership (including all ten locked instruments in
the Wave 2 acceptance universe), effective-time cutoff, knowledge-time cutoff,
node records, relationship definitions, and edge states. Economic entities and
tradeable instruments use separate node kinds; external context nodes such as
regulators, events, and geographies are valid even when they are outside the
locked trading universe.

Relationship definitions state whether edges are directed or symmetric. Edge
states hold effective and knowledge intervals independently, evidence IDs,
confidence, economic exposure, propagation coefficient, lifecycle, and strategy
eligibility. A snapshot validates endpoint and relation references, unique IDs,
and duplicate symmetric links. All timestamps are timezone-aware.

## Persistence and replay

PostgreSQL is the durable source of truth in `temporal_graph_snapshots`. Each row
contains a full canonical JSON payload, digest, workspace/universe keys, and both
time cutoffs. Database triggers reject updates and deletes. Reusing a snapshot ID
with different content fails; repeating the same publication is idempotent.
`InMemoryTemporalGraphRepository` mirrors these semantics for offline development
and tests. The repository contract exposes `latest`, `get`, `list`, `publish`,
and bitemporal `replay`.

Replay selects the latest complete snapshot that had been published by the
requested knowledge time, then filters edge states by both effective and
knowledge intervals. Thus newly collected evidence can affect later snapshots
without rewriting a historical snapshot or appearing in a replay that predates
its publication/knowledge time. Snapshot diffs compare stable record IDs and
return sorted added, removed, and changed ID tuples.

## Analysis and compatibility

NetworkX is loaded only through the bounded `BoundedGraphAnalysis` adapter for
centrality, weak components, and directed shortest paths. It is not used to store
graphs or establish persistence semantics. The optional visualization dependency
is reused. Existing `graph_registry` and `RippleRiskScorer` v1 records and behavior
are left intact; migration 003 adds a separate table and does not alter legacy
tables or payloads.

## Limits

The graph table stores a canonical full snapshot payload rather than normalized
node/edge rows. This keeps publication atomic and snapshots self-contained, while
queries that need historical graph state currently load a selected snapshot and
filter its edge-state tuple in the application. The graph analysis adapter has
explicit node and edge bounds and is diagnostic only; it does not certify an
economic relationship or make a strategy eligible.
