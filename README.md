# Agentic Alpha Studio

An open-source, local-first application for turning a market domain into a reproducible strategy workflow:

`Domain → Universe → Graph → Alpha → Backtest → Paper / LEAN Export → Monitor`

The product is being built for production use, with durable jobs, versioned inputs, and observable automation. The current safety boundary is paper deployment and reproducible LEAN export; it does not place live orders.

## Wave 1 foundation

- Immutable product contracts for domain workspaces, universes, instruments, providers, strategies, runs, packages, and readiness.
- PostgreSQL repositories and ordered migrations for durable versioned records.
- Redis-backed, restart-safe jobs with idempotent dispatch, progress events, cancellation, and durable receipts.
- A local credential-vault boundary that keeps secrets out of application records and logs.
- FastAPI endpoints for workspace creation and job progress.
- A responsive React application shell using React Router, TanStack Query, Tailwind, and Radix, with a clearly labeled offline demo fallback.
- The earlier evidence, graph, alpha, backtest, Gatekeeper, Monitor, and bounded orchestration modules remain available while they are migrated into the production workflow in later waves.

## One-command local stack

Install and start Docker Desktop, then double-click `start-studio.cmd`, or run:

```powershell
.\scripts\start-studio.ps1 -Build
```

This starts PostgreSQL, Redis, the API, worker, and web application on localhost. Open `http://127.0.0.1:5173`. The LEAN worker is only a disabled future profile in Wave 1.

## Developer setup

Python 3.11+ and Node.js 22+ are supported. For the simplest Windows Python setup, double-click `setup.cmd`. Then install the web dependencies once:

```powershell
cd web
npm ci
```

Run the verification suite from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
cd web
npm run build
npm test
```

Normal tests use in-memory repositories and fixtures. Set `TEST_POSTGRES_DSN` only when you want to run the optional live PostgreSQL repository test.

## Workflow

Before every shared work session, update `main` and read [PROJECT_STATE.md](docs/PROJECT_STATE.md). Commit and push every verified slice, including the relevant test and documentation update. See [AGENTS.md](AGENTS.md) for the full working agreement.

## Safety and scope

This software does not provide investment advice. Wave 1 has no live-broker or live-order route. Free market-data adapters remain development conveniences rather than production-data claims. Credentials belong in the local OS vault or ignored `.env`, never Git.


