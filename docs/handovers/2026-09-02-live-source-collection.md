# Handover — live source collection

Commits `6b0a454`, `0895ca7`, and `5d3d87a` added and hardened the bounded
whole-source evidence collector. Both local provider settings are configured
only in ignored `.env`.

The real run is recorded in
`docs/research/2026-09-02-live-source-collection.md`. Do not commit the local
DuckDB ledger, HTTP caches, provider keys, or raw run output. Before beginning
the next slice, pull `main`, read that source-run report and `PROJECT_STATE.md`,
then address source fallback reliability before granting greater graph autonomy.
