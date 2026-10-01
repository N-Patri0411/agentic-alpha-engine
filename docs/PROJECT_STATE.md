# Project State

## Current milestone

Wave 2 — Provider-aware Domain and Universe onboarding implemented and verified
(2026-09-30), building on the Wave 1 product foundation.

Agentic Alpha Studio now has the shared contracts, durable storage model, job
runtime, local service stack, API boundary, and production application shell
required by every later product wave. Wave 2 adds bounded provider contracts,
instrument discovery and mapping, historical coverage scoring, current/PIT
selection, company replacement, and durable universe locking. Graph v2, LEAN
compilation, and deployment automation have not started.

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
- Provider configuration checks report local credential presence only; they do
  not probe connectivity or account readiness. Current providers do not claim
  point-in-time discovery, so PIT requests receive an actionable API rejection.
- Discovery yield is separate from measured historical data coverage. Provider
  exceptions produce safe warnings while retaining other providers' results.
  Universe reads use a typed persistence interface, and workspace/universe lock
  writes are atomic in PostgreSQL and rollback-safe in memory.

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

Current results: 181 Python tests passed, 1 live-PostgreSQL integration test
skipped without `TEST_POSTGRES_DSN`; Ruff and strict mypy passed; the web
production build passed; 9 Vitest/Testing Library tests passed, including the
axe accessibility check and domain/universe onboarding flow.

## Next slices, in order

1. Run the Compose stack on a machine with Docker Desktop and execute the
   optional live PostgreSQL repository test.
2. Extend provider breadth for fundamentals, corporate actions, calendars, FX,
   evidence documents, and a source that guarantees historical discovery.
3. Connect locked universes to graph v2 and continue into alpha/backtest flows.

## Known limitations and boundaries

- Docker is not installed or available in the current execution environment,
  so Compose structure, migration order, health gates, and localhost bindings
  are covered by static tests but the complete container stack was not launched.
- The PostgreSQL round-trip test is opt-in and was skipped locally. Normal tests
  use the contract-equivalent in-memory repositories.
- The live provider credentials are not configured in this test environment;
  provider connectivity was intentionally not probed.
- Most workflow pages beyond Domain are polished Wave 1 shells with visibly
  labeled demo data. They do not yet claim production graph, alpha, LEAN, or
  deployment behavior.
- Paper deployment and LEAN export are the approved execution boundary. There
  is no live broker integration or live-order path.
- `.env`, provider keys, private/licensed data, caches, `node_modules`, built
  assets, and local service volumes are not tracked by Git.
