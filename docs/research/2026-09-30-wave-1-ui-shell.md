# Wave 1 UI shell

## Outcome

The `web/` application is an Agentic Alpha Studio production-strategy shell,
implemented with React, React Router, TanStack Query, Tailwind CSS, and a Radix
Dialog. Its route sequence is explicit and consistent across navigation and
page actions:

`Domain → Universe → Graph → Alpha → Backtest → Paper / LEAN Export → Monitor`

The graph workflow is autonomous. The interface exposes job progress and
deterministic safeguards; it does not introduce a human-review or approval
queue. Paper output remains non-live and LEAN is an export target.

## API boundary and demo fallback

The UI uses the Wave 1 API contracts directly:

- `GET /api/health` for local runtime availability.
- `GET /api/workspaces` for Home and the current domain.
- `POST /api/workspaces` followed by `POST /api/jobs` with the supported
  `workspace-bootstrap` kind on New Domain.
- `GET /api/jobs` for the global jobs drawer and Monitor.

The typed API client is isolated in `web/src/api.ts`. If any shell query cannot
reach the local API, the interface remains usable with local fixtures. That
state is visibly identified as `Demo fallback`, and fixture values are marked
`DEMO`; demo identifiers are never presented as API records.

The browser always calls relative `/api` paths. During development, Vite proxies
those requests to `VITE_API_BASE_URL` when supplied (for example,
`http://api:8000` inside Compose), with `http://127.0.0.1:8000` as the local
workstation fallback.

## Responsive and accessibility behavior

The desktop sidebar becomes an off-canvas navigation below 1024 pixels. The
strategy flow changes from seven to four columns and then two columns on narrow
screens, while entity and metric grids collapse without horizontal scrolling.
The application includes a skip link, visible focus states, named icon buttons,
semantic landmarks, reduced-motion support, and a focus-managed Radix job
dialog. Vitest covers routing content, offline labeling, workspace/job writes,
the jobs dialog, and an axe scan of the Home shell.

## Dependency checkpoint

The manifest and lockfile use pinned package versions. The lockfile was
regenerated after installing the Wave 1 dependency set; repeatable local and
container builds now use `npm ci`.
