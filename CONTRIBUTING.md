# Contributing

## Shared work protocol

1. Update `main`, then read `docs/PROJECT_STATE.md`.
2. Pick one small slice with an observable acceptance check.
3. Make the smallest focused change; add or update its test in the same slice.
4. Run the documented checks.
5. Update project state and any affected research or decision record.
6. Commit and push the verified slice before moving to another laptop.

Never commit credentials, data under restrictive licenses, downloaded caches, or generated reports. The local `andrej-karpathy-skills` checkout is intentionally ignored; enable it on each machine and rely on the tracked root `AGENTS.md` for repository-scoped behavior.

## Research integrity

An experiment report must identify its input snapshot, as-of timestamp, costs, validation method, and limitations. A passing test proves code behavior only; it does not prove an alpha works economically.
