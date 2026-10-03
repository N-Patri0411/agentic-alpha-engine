# Wave 4 backend integration

## Integration boundary

`server.alpha_api` adapts the existing deterministic DSL and injected
`AlphaGeneratorService` into workspace-scoped endpoints. Generation and strategy
validation first resolve the workspace's immutable universe and graph snapshot,
then require explicit workspace feature bindings that are ready at the graph's
as-of time. Feature definitions alone never imply availability.

Bindings are append-only per workspace, feature, and binding version. The
separate feature version identifies the deterministic feature schema, so a new
dataset refresh can create a new binding without rewriting history. They pin
feature and dataset versions, availability time, source artifacts, and optional
graph snapshot ID/digest. Strategy versions use the existing product repository;
their stable identity is `strategy_id`, with increasing immutable versions.
Candidate formulas are canonicalized before append-only experiment accounting;
PostgreSQL serializes counter updates with a transaction advisory lock and
deduplicates formulas per experiment.

The in-memory dependency factory injects `FakeLLMClient` and an in-memory trial
ledger. PostgreSQL runtime construction loads the provider-neutral
`alpha_generator` role and uses the durable ledger. API errors deliberately
omit provider exception text so credentials or request material are not exposed.
`/api/strategies/validate` reports deterministic contract checks and explicitly
reports that it did not run a backtest.

## Current readiness and migration notes

No feature computation is wired to the product data flow yet, so new workspaces
correctly report features unavailable until a trusted caller persists a binding.
Migration `004_features.sql` adds explicit versioned binding and trial tables alongside
the feature artifact store. It uses `CREATE TABLE IF NOT EXISTS`, primary keys,
payload identity checks, and immutable-row triggers. Existing databases need
the normal migration runner to apply the expanded migration; the migration was
not exercised against a live PostgreSQL server in this environment.

The strategy model adds `feature_version_ids`; this is optional for old records.
The repository identity selection now keys StrategySpec versions by
`strategy_id` (rather than the containing workspace), which is necessary for
version history to work.
