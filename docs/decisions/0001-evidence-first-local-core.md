# ADR 0001: Use an evidence-first local core

## Status

Accepted, 2026-08-31.

## Decision

Build a Python-first local research core before adding autonomous orchestration, hosted collaboration, or broker integration. Every research result must identify its code version, input snapshots, feature availability, validation policy, and costs.

## Consequences

- The first release is paper research only.
- LLMs may propose constrained hypotheses but cannot produce trade instructions.
- DuckDB, a network client, and advanced orchestration are deferred until a demonstrated milestone needs them.
- Negative or inconclusive experiments remain valuable, tracked artifacts.
