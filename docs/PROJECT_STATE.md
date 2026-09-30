# Project State

## Current milestone

Wave 1 — Product Foundation implemented and verified (2026-09-30).

Agentic Alpha Studio now has the shared contracts, durable storage model, job
runtime, local service stack, API boundary, and production application shell
required by every later product wave. Domain discovery, graph v2, LEAN
compilation, and deployment automation have deliberately not been started in
this milestone.

## What works now

- Immutable Pydantic contracts cover domain workspaces, current or
  point-in-time universes, instruments, provider capabilities, strategies,
  strategy runs, packages, and readiness reports. Canonical serialization and
  hashes make versions reproducible.
- Product records are append-only in PostgreSQL. A logical ID/version cannot be
  overwritten, and latest workspace listing is repository-backed rather than
  process-local.
- `alpha_workbench.jobs` is the sole operational job boundary. Redis dispatch
  is idempotent, processing jobs can be reclaimed after a worker restart, and
  receipts/events remain durable in PostgreSQL.
- The bounded `workspace-bootstrap` job reports deterministic progress. The
  API exposes health/readiness, workspace create/list/get, job
  create/list/get/events/cancel, plus legacy run endpoints.
- Secrets use an OS-keyring abstraction and redacted values. Secrets and job
  payloads are not returned in health, receipts, or event responses.
- `start-studio.cmd` starts PostgreSQL, migrations, Redis, API, worker, and web
  services through Docker Compose. Published ports bind to `127.0.0.1` only;
  the future LEAN worker is disabled behind a profile.
- The React shell implements the full product navigation:
  `Domain → Universe → Graph → Alpha → Backtest → Paper / LEAN Export → Monitor`.
  New Domain creates a workspace and starts its bootstrap job. The global job
  drawer reloads durable status. If the local API is unavailable, fixtures are
  explicitly marked `DEMO`.
- The earlier evidence ingestion, living-graph experiments, alpha generation,
  deterministic backtesting, Gatekeeper, Monitor, and bounded Orchestrator
  remain intact and tested. They are not yet wired into the new product pages.

## Verified commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
cd web
npm ci
npm run build
npm test
```

Current results: 157 Python tests passed, 1 live-PostgreSQL integration test
skipped without `TEST_POSTGRES_DSN`; Ruff and strict mypy passed; the web
production build passed; 5 Vitest/Testing Library tests passed, including the
axe accessibility check and create-workspace/bootstrap flow.

## Next slices, in order

1. Run the Compose stack on a machine with Docker Desktop and execute the
   optional live PostgreSQL repository test. This is the remaining Wave 1
   environment acceptance check.
2. Begin Wave 2 with provider-neutral instrument discovery, identifier mapping,
   historical bars, fundamentals, corporate actions, calendars, FX, and
   evidence-document capability reports.
3. Build Domain and Universe agents against those provider contracts, including
   current versus point-in-time selection, liquidity/coverage scoring, ten-name
   recommendations, user replacement, and locking.
4. Complete the onboarding wizard only after the Wave 2 backend contracts are
   stable. Do not begin graph v2, LEAN compilation, or production deployment in
   parallel with unfinished provider/universe foundations.

## Known limitations and boundaries

- Docker is not installed or available in the current execution environment,
  so Compose structure, migration order, health gates, and localhost bindings
  are covered by static tests but the complete container stack was not launched.
- The PostgreSQL round-trip test is opt-in and was skipped locally. Normal tests
  use the contract-equivalent in-memory repositories.
- Most workflow pages beyond Domain are polished Wave 1 shells with visibly
  labeled demo data. They do not yet claim production graph, alpha, LEAN, or
  deployment behavior.
- Paper deployment and LEAN export are the approved execution boundary. There
  is no live broker integration or live-order path.
- `.env`, provider keys, private/licensed data, caches, `node_modules`, built
  assets, and local service volumes are not tracked by Git.
