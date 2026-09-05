# 0006 — Bounded candidate evidence graph

## Status

Accepted, 2026-09-04.

## Context

An initial semiconductor registry is necessary for reliable source collection,
but a fixed list cannot describe every relevant customer, partner, competitor,
or supplier. Treating only the initial ten companies as possible entities makes
the map artificially sparse. Conversely, allowing every extracted proper noun
to create more searches and edges makes source quality, cost, and graph scope
uncontrollable.

## Decision

Create a separate candidate-evidence graph alongside reviewed graph snapshots.
It always includes the reviewed anchor registry. A direct, source-quoted
relationship may add one discovered entity when it connects to an anchor. It is
not allowed to add a relationship between two discovered entities or trigger
another round of expansion. Candidate nodes and edges are clearly marked and
carry their evidence, availability time, type, rationale, and model-suggested
confidence.

The candidate graph is not a `RippleRiskScorer` input. It cannot update the
registry, overwrite a snapshot, or become a portfolio signal. Promotion remains
the Graph Adjudicator's responsibility, using relationship-specific evidence
rules. Manufacturing, equipment, and packaging candidates are merely marked as
potentially scenario-eligible after review; competition, customer concentration,
and collaboration remain descriptive until policies define a causal scenario
interpretation.

## Consequences

The project can show a much fuller industry map while preserving an auditable,
small scenario graph. It also gives the extractor a high-recall target without
making the LLM the system of record. The next slice must wire candidate
discovery to a bounded manual source run and define promotion rules per
relationship type.
