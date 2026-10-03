# Project State

## Current milestone

Wave 3 — Evidence-backed temporal graph runtime implemented and locally verified
(2026-10-02), building on Wave 1 and Wave 2.

Agentic Alpha Studio now has the shared contracts, durable storage model, job
runtime, local service stack, API boundary, and product shell. Wave 2 adds bounded
provider contracts, instrument discovery and mapping, historical coverage
scoring, current/PIT selection, company replacement, and durable universe
locking. Wave 3 adds immutable temporal graph snapshots, graph refresh jobs,
evidence cutoff enforcement, deterministic relationship policy, REST/UI graph
projection, and a graph exploration page. LEAN compilation and deployment
automation have not started.

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
- Temporal graph snapshots are append-only, bitemporal, and stored in
  PostgreSQL in the local runtime. Graph refresh is an idempotently submitted
  durable job; empty evidence publishes only locked-universe nodes. Extracted
  proposals must pass exact-quote/entity validation, while deterministic policy
  alone controls edge eligibility and weights.

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

Current results: 205 Python tests passed, 1 live-PostgreSQL integration test
skipped without `TEST_POSTGRES_DSN`; Ruff and strict mypy passed; the web
production build passed; 14 Vitest/Testing Library tests passed. The graph page
includes an axe accessibility check. The build reports a large JavaScript chunk
warning (about 812 kB before gzip).

A bounded paid smoke test made exactly two Luna extraction calls over existing
official ASML/TSMC ledger evidence. Luna produced one valid `ASML → TSM`
equipment-dependency proposal and one no-proposal result. Exact-quote validation
passed; deterministic policy kept the single-source edge strategy-ineligible for
insufficient independent corroboration.

## Next slices, in order

1. Run the Compose stack on a machine with Docker Desktop and execute the
   optional live PostgreSQL repository test.
2. Connect graph snapshots to the Alpha and Backtest product flows.
3. Extend provider breadth for fundamentals, corporate actions, calendars, FX,
   evidence documents, and a source that guarantees historical discovery.

## Known limitations and boundaries

- Docker is not installed or available in the current execution environment,
  so Compose structure, migration order, health gates, and localhost bindings
  are covered by static tests but the complete container stack was not launched.
- The PostgreSQL round-trip test is opt-in and was skipped locally. Normal tests
  use the contract-equivalent in-memory repositories.
- The paid extraction provider path was verified with two bounded Luna calls,
  but that smoke test does not establish broad extraction quality. Docker
  Compose and the migration were not run against live PostgreSQL in this
  environment.
- The live provider credentials are not configured in this test environment;
  provider connectivity was intentionally not probed.
- Alpha, Backtest, Paper/LEAN Export, and Monitor remain demo/product shells and
  are not yet connected to the Wave 3 graph runtime.
- Paper deployment and LEAN export are the approved execution boundary. There
  is no live broker integration or live-order path.
- `.env`, provider keys, private/licensed data, caches, `node_modules`, built
  assets, and local service volumes are not tracked by Git.
