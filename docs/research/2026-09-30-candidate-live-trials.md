# Candidate graph live trials — 2026-09-30

Two bounded candidate-graph trials were run against the local source ledger on
2026-09-30. Their JSON outputs are ignored local artifacts and are documented
here for reproducibility without redistributing source payloads.

## V3 official-source trial

Artifact: `artifacts/candidate-wide-2026-09-30.json`.

The run selected eight official observations and produced 10 registry anchor
nodes, seven candidate edges, and zero ignored relationships. The candidate
relationships were:

| Source | Target | Type | Suggested confidence |
| --- | --- | --- | ---: |
| ASML | TSM | strategic collaboration | 0.98 |
| ASML | Samsung | strategic collaboration | 0.98 |
| MU | NVDA | strategic collaboration | 0.94 |
| AMD | GFS | manufacturing dependency | 0.95 |
| NVDA | Samsung | strategic collaboration | 0.98 |
| TSM | ASML | strategic collaboration | 0.99 |
| TSM | ASML | equipment dependency | 0.98 |

All seven edges are marked `candidate`; none is a reviewed snapshot edge.
The source-tier selection count reported for this trial was eight official
observations. The artifact preserves each URL, quote, availability time,
observation ID, source kind, and adapter.

## Broad-source trial

Artifact: `artifacts/candidate-broad-2026-09-30.json`.

The run selected eight text observations across two discovery and six official
sources. It retained all 10 registry anchors and added one discovered node,
Tata Electronics, for 11 nodes total. It produced one candidate edge and zero
ignored relationships:

| Source | Target | Type | Suggested confidence |
| --- | --- | --- | ---: |
| Tata Electronics | ASML | strategic collaboration | 0.99 |

The discovered source is represented as `candidate:tata-electronics`; the edge
is unapproved and not scenario-eligible. The artifact records the source as an
official investor-relations observation with full-text evidence, even though
the bounded input mix also included two discovery observations.

## Interpretation and limitations

These runs demonstrate candidate recall and provenance flow, not graph
completeness or economic validity. Ten anchors remain visible by construction,
but there is no guarantee that all anchors become connected: the broad trial
connected only Tata Electronics to ASML, and candidate edges require later
validation and adjudication before promotion. Relationship types are model
hypotheses, including generic collaborations; the candidate layer does not
turn them into approved scenario dependencies. The official trial also shows
that multiple candidate relationships can share one source passage, so edge
counts are not independent-source counts. No paid follow-up calls were made
as part of this documentation.
