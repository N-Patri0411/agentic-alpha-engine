# 2026-09-04 — Candidate graph and high-recall extraction overhaul

## Aim

Make the semiconductor map more complete without converting unverified web or
LLM output directly into a scenario or trading graph.

## Change

The deterministic passage selector now considers explicit language for
competitors, competitive substitution, named customers, design wins, equipment,
joint development, licensing, and collaborations alongside manufacturing and
supply-chain terms. This improves recall: a relevant passage need not use the
word "supplier" to be selected.

The model-facing extractor can preserve names outside the fixed registry. The
candidate graph resolves aliases for the ten anchors, then adds at most one
external company one relationship away from an anchor. It rejects
external-to-external links and never writes a reviewed graph snapshot.

## Interpretation

This is a discovery capability, not proof that a relationship exists or that it
has predictive value. Source passage, source tier, availability time, and
relationship-specific adjudication remain required before an edge can affect a
scenario. The visualizer now makes those later decisions inspectable by showing
all current edge state numbers and review information locally.
