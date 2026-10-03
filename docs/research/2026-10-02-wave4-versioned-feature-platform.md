# Wave 4 — Versioned Feature Platform

## Contract and provenance

`alpha_workbench.features` defines immutable `FeatureDefinition` schemas,
versioned `FeatureSetVersion` selections, timestamped input and output
observations, and `FeatureFrameManifest` build receipts. A feature set pins
definition versions, source dataset versions, and (for graph features) both the
temporal graph snapshot ID and its content digest. A manifest records the same
pins, the feature-set digest, per-definition digests, and three clocks:
decision `as_of_time`, graph `effective_time`, and graph `knowledge_time`.

Input observations require timezone-aware `observed_at` and `available_at`,
with availability no earlier than observation. Builders reject any future row,
dataset version mismatch, or frequency mismatch. Each feature returns a
per-feature readiness result; missing data, absent pins, or insufficient values
are reported as `unavailable` with a reason instead of synthetic placeholder
values.

## Deterministic catalog

The built-in catalog contains executable deterministic builders for graph
propagation exposure, neighbor signal lag, graph degree centrality and exposure
concentration, lagged correlation, price return and volume change, realized
volatility, gross margin and return on assets, earnings surprise and 30-day event
count, sentiment drift, macro change, and FX return. Source-dependent families
consume frozen `FeatureInputFrame` fixtures so tests run offline. No adapter is
advertised as having collected production source data.

Graph builders require the pinned v2 snapshot. They evaluate bitemporal states
at the effective and knowledge cutoffs and include only active,
strategy-eligible edge states. Graph-derived output rows carry the pinned
snapshot ID and digest. The decision cutoff is the later of graph effective
time and publication time, so output is never available before its snapshot is
published. Alpha readiness uses that same decision cutoff. Historical graph
changes therefore produce a distinct manifest and a new workspace binding
version.

`POST /api/workspaces/{workspace_id}/feature-refresh` submits an idempotent
`feature-refresh` job through the shared durable job runner. The worker checks
workspace, locked-universe, and pinned-graph ownership; stores the built-in
definitions, graph-pinned feature set, observations, and manifest; and appends
per-feature readiness bindings. Identical semantic bindings are not versioned
again. Graph propagation and centrality can become ready from the graph alone;
neighbor signal lag remains unavailable without a signal frame, and market,
fundamental, event, language, and macro features remain unavailable without
their source frames.

## Persistence and verification boundary

The in-memory and DB-API PostgreSQL repositories append definitions, feature
sets, content-addressed feature observations, and full frame manifests. Migration `004_features.sql` uses a versioned
primary key and rejects update/delete operations. Ordinary tests cover all
catalog families, point-in-time rejection, incompatible frequencies and dataset
versions, graph-version pinning, deterministic frame hashes, and append-only
repository behavior without a live database.

Dataset frames are supplied by callers; workspace refresh currently builds only
graph-derived features and does not connect provider adapters. Alpha generation
can consume a ready graph binding, but backtesting is not connected. The
PostgreSQL migration and repository SQL shape have static/recording-cursor
coverage, but have not been round-tripped against a live PostgreSQL service.
