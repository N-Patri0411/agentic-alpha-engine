# Project State

## Current milestone

Wave 4 — Alpha feature and strategy backend flow integrated and locally verified
(2026-10-03), building on Waves 1 through 3.

Agentic Alpha Studio now has the shared contracts, durable storage model, job
runtime, local service stack, API boundary, and product shell. Wave 2 adds bounded
provider contracts, instrument discovery and mapping, historical coverage
scoring, current/PIT selection, company replacement, and durable universe
locking. Wave 3 adds immutable temporal graph snapshots, graph refresh jobs,
evidence cutoff enforcement, deterministic relationship policy, REST/UI graph
projection, and a graph exploration page. Wave 4 adds a workspace feature
catalog with explicit readiness bindings, bounded alpha generation with
durable trial accounting, DSL and pin validation, and immutable strategy
version routes. LEAN compilation and deployment automation have not started.

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
- Alpha routes validate workspace, locked universe, graph ownership, and
  point-in-time feature bindings before generation or strategy validation.
  Workspace bindings and experiment trial counts have append-only PostgreSQL
  storage; strategy versions are keyed by strategy ID and cannot be overwritten.
  Validation is deterministic contract checking and never claims to run a
  backtest.
- Workspace feature refresh is submitted through the durable job runner. The
  worker persists deterministic graph-derived feature definitions, sets,
  observations, manifests, and versioned readiness bindings against the locked
  universe and pinned graph. Graph propagation and centrality can become ready
  from graph data alone; neighbor lag and all market/fundamental/event/language/
  macro families remain unavailable without their source frames.
- In-memory API dependencies inject a deterministic fake model client. The
  PostgreSQL runtime builds the configured provider-neutral `alpha_generator`
  role. Provider error details are not returned by the API.
- Alpha Studio now exposes the workspace feature browser, guided candidate
  generation, constrained DSL editing, deterministic validation, immutable
  strategy history, and side-by-side alternatives. A locally bundled Monaco
  editor is lazy-loaded only when reviewed hash-pinned Python extensions are
  explicitly enabled; that capability is off by default.

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

Current results after the CI-hermeticity follow-up: 238 Python tests passed,
1 live-PostgreSQL integration test skipped without `TEST_POSTGRES_DSN`; Ruff
and strict mypy passed. The web production build passed and 26
Vitest/Testing Library tests passed. The build reports large chunks from the
existing editor dependencies.

`verify.cmd` now reproduces the GitHub Python checks, clean npm install, web
production build, and web tests locally. `setup.cmd` enables a tracked pre-push
hook so failed verification blocks a push on each configured laptop. Cloud
tests inject offline fixtures instead of depending on the ignored `.env` or
`data/private/evidence.duckdb`; real paid smoke runs still require those local
inputs explicitly.

A bounded paid smoke test made exactly two Luna extraction calls over existing
official ASML/TSMC ledger evidence. Luna produced one valid `ASML → TSM`
equipment-dependency proposal and one no-proposal result. Exact-quote validation
passed; deterministic policy kept the single-source edge strategy-ineligible for
insufficient independent corroboration.

A separate bounded Wave 4 smoke made exactly one paid Luna call after building
a point-in-time feature manifest from 1,400 locally collected market bars. The
manifest covered eight semiconductor symbols and pinned `close_return` and
`volume_change`. Luna returned three formulas; deterministic DSL validation,
feature-pin checks, deduplication, and the three-trial ceiling all passed. This
verifies the generation path, not economic value or future performance.
The local daily-cost reservation is serialized across concurrent callers, and
an exhausted experiment is rejected before another model call is made.

## Next slices, in order

1. Run the Compose stack on a machine with Docker Desktop and execute the
   optional live PostgreSQL repository test.
2. Connect feature builders to workspace datasets and add historical strategy
   evaluation from the saved StrategySpec contract.
3. Extend provider breadth for fundamentals, corporate actions, calendars, FX,
   evidence documents, and a source that guarantees historical discovery.

## Known limitations and boundaries

- Docker is not installed or available in the current execution environment,
  so Compose structure, migration order, health gates, and localhost bindings
  are covered by static tests but the complete container stack was not launched.
- The PostgreSQL round-trip test is opt-in and was skipped locally. Normal tests
  use the contract-equivalent in-memory repositories.
- Wave 4 migration additions and PostgreSQL trial-counter concurrency were not
  exercised against a live database. Workspace refresh is not connected to
  market or fundamental data ingestion and makes no readiness claim for those
  feature families.
- The paid extraction provider path was verified with two bounded Luna calls,
  but that smoke test does not establish broad extraction quality. Docker
  Compose and the migration were not run against live PostgreSQL in this
  environment.
- The OpenAI credential was used only for the explicitly authorized, locally
  budgeted Wave 3 and Wave 4 smoke calls. Other provider connectivity was not
  probed during this milestone.
- Backtest, Paper/LEAN Export, and Monitor remain demo/product shells and are
  not yet connected to saved Wave 4 strategies.
- Paper deployment and LEAN export are the approved execution boundary. There
  is no live broker integration or live-order path.
- `.env`, provider keys, private/licensed data, caches, `node_modules`, built
  assets, and local service volumes are not tracked by Git.
