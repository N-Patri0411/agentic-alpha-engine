# Agentic Alpha Research Workbench

This repository is the shared, durable source of truth for the project. Work must be reproducible from tracked code, documentation, and fixtures; do not rely on local agent memory, caches, or uncommitted notes.

## Working Discipline

Apply these checks to every non-trivial task:

1. Think before coding. State meaningful assumptions and choose the smallest safe interpretation.
2. Keep it simple. Build only the slice required by the current milestone; do not add agents, vendors, or infrastructure before an acceptance test needs them.
3. Make surgical changes. Keep changes focused and do not mix formatting or unrelated cleanup into behavior work.
4. Define and verify the goal. Each slice needs an observable outcome and the narrowest useful verification.

## Shared Git Workflow

- Before work: update `main`, read `docs/PROJECT_STATE.md`, and inspect the working tree.
- Work on one independently testable slice at a time.
- Update code, tests, and relevant state/research documentation together.
- Commit only work tied to the active slice and push after verification.
- If synchronization fails, resolve it before beginning another slice.
- Never commit credentials, licensed/private data, local caches, or machine-specific paths.

## Research Integrity

- Every time-sensitive observation needs `observed_at`, `available_at`, and an explicit research `as_of_time`.
- A backtest must reject data that was unavailable at its as-of time.
- Tests establish software correctness, not economic validity. Report out-of-sample results honestly, including negative results.
- LLMs may propose typed hypotheses; they do not issue trading instructions.
- The application is paper-research software, not investment advice or a live trading system.

## Definition of Done

For a normal slice, report: assumption, changed behavior, verification, and remaining risk. Update `docs/PROJECT_STATE.md` whenever the current milestone or verified commands change.
