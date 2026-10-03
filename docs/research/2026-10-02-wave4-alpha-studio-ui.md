# Wave 4 Alpha Studio UI slice

Observed 2026-10-02. The former `/alpha` route in `web/src/App.tsx` was a static two-card demonstration. The Wave 3 API client exposes locked workspace IDs and graph snapshot summaries, but this checkout had no Alpha feature, candidate, strategy, version, or deterministic validation routes wired to the UI when this slice began.

## Interaction contract implemented

- The feature browser normalizes both the anticipated catalog envelope (`features`) and the existing point-in-time feature shape (`name`, `description`, `entity_scope`, `available_at`, `source_artifact_ids`). Features marked unavailable/blocked cannot be selected. Frequency, provenance, readiness, and a disabled reason are shown when supplied.
- Candidate generation sends intent, selected feature names, locked universe ID, pinned graph snapshot ID, portfolio controls, and risk controls to `POST /api/workspaces/{workspace_id}/alpha-candidates`.
- Candidate expressions are editable in the restricted DSL text editor. `POST /api/strategies/validate` is surfaced as deterministic contract validation and explicitly not as a backtest. `POST /api/workspaces/{workspace_id}/strategies` saves a version; `GET /api/strategies/{strategy_id}/versions` fills the history.
- API failures and missing catalog data are labeled as DEMO. A missing locked universe or graph snapshot blocks candidate generation, validation, and save.
- Advanced Python is visibly disabled unless `VITE_ALPHA_HASH_PINNED_EXTENSIONS_ENABLED=true` is explicitly configured. When enabled, Monaco is lazy-loaded from pinned local npm packages and is not part of the initial route bundle. Python source remains a separate draft; the constrained DSL above remains the strategy expression used for validation and version saves.
- The Graph route now loads on demand so Cytoscape does not inflate the initial application chunk.

## API expectations to align

The UI currently expects feature catalog records to provide `name`, optional `category` or `entity_scope`, `description`, `available` or `readiness`, optional measured `frequency`, `provenance` or `source_artifact_ids`, and optional `reason`/`unavailable_reason`. Candidate generation may return an array or `{ candidates: [...] }`; candidates should include `candidate_id`, `name`, `expression`, `rationale`, `feature_names`, and `status`. Version records should expose `strategy_id`, `version`, `name`, `expression`, `created_at`, and `status`. Validation should expose `valid` (or `ok`/`status: passed`), plus an optional `message` or `checks` list.

No direct paid model call is made by this UI. The candidate endpoint is the bounded backend boundary and must label paid-model provenance and usage in its own result. Candidate generation should reject a workspace context whose universe/snapshot no longer matches the selected locked records.

## Limitations

The hash-pinned extension capability remains off by default; the flag is an explicit frontend capability gate, not a substitute for backend review or registration. The DSL editor remains usable without introducing arbitrary Python execution. Monaco assets and language workers are bundled locally in the lazy advanced-editor chunks, with no CDN loader path.

Verification on 2026-10-03: `npm test` passed (21 tests) and `npm run build` passed. The initial application chunk is 368 kB (115 kB gzip), and the graph route remains separate at 463 kB (148 kB gzip). The opt-in Python editor is a separate 3.32 MB chunk (853 kB gzip); its local workers are separate assets, including a 6.01 MB TypeScript worker not used by the Python editor. No initial-bundle increase from Monaco was observed. The server capability contract and extension registration lifecycle remain backend work.
