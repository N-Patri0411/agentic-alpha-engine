# Wave 2 domain onboarding UI

Observed at: 2026-09-30

The Domain onboarding flow now gathers a strategy description, regions, update
cadence, base currency, and a selection mode. Current mode asks the API to use
the latest eligible information (`selection_time: null`). Point-in-time mode
requires a local date and time, converts it to UTC, and displays the resolved
UTC timestamp returned by the plan API.

The UI uses the agreed Wave 2 API boundary:

- `GET /api/providers/capabilities`
- `POST /api/providers/check`
- `POST /api/domain-plans`
- `POST /api/domain-plans/{plan_id}/replace`
- `POST /api/domain-plans/{plan_id}/lock`

The request and response types and normalization helpers live in
`web/src/api.ts`. The normalizer maps the backend's flat percentage score
fields, company names, methodology list, and provider coverage map into the UI
view types. Provider setup shows configured status, coverage, and limitations.
It does not collect or render credential values. The plan review shows
selection methodology and timestamp, company reasons and component scores,
FIGI and exchange, provider coverage, and rejected/unavailable candidates.
Eligible replacement options are shown only when returned in
`replacement_candidates`; the UI does not accept unverified IDs. Locking the
plan creates the workspace and starts its existing bootstrap job.

If the local service is offline, the wizard uses labeled `DEMO` fixtures and
does not represent them as provider results. When an individual plan endpoint
is unavailable while the broader service is reachable, the user sees the
failure and can explicitly switch to demo data.

The frontend tests exercise the full flow, provider-check failure, replacement,
locking/workspace creation, keyboard navigation, axe checks, and a 1024px
viewport. They use mocked API responses. The real backend integration still
requires the Wave 2 services to be available and the agreed wire shapes to be
verified against the running local stack.
