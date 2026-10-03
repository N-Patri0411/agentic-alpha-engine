# Wave 3 Graph Runtime Integration

## API and durable job path

The graph API lists a workspace's immutable snapshots, returns a normalized UI
snapshot and edge states, compares two snapshots, and submits a `graph-refresh`
job. Snapshot storage is available in memory for tests and PostgreSQL in the
local Compose runtime. The temporal graph migration is included in the existing
ordered migration mount. The API returns the durable job receipt; the worker can
resume the same queued payload after restart. A caller-provided idempotency key
returns the original receipt on retry.

Graph refresh loads the workspace's locked `UniverseSpec`, obtains observations
from `data/private/evidence.duckdb` (or `ALPHA_EVIDENCE_DB`), applies the durable
job's as-of timestamps, and invokes the autonomous graph pipeline. Inputs are
limited to evidence available by `as_of_time` and actually retrieved by
`knowledge_time`, so both public availability and local knowledge obey the
requested cutoffs. Missing or
empty evidence yields a node-only snapshot with zero eligible relationships and
an explicit job progress warning. The job does not create sample edges. Event and
nightly pipeline entry points remain callable separately.

## Extraction and eligibility

The `GraphInputProvider` is injectable so tests and local integrations can
provide frozen observations and model responses. The default DuckDB provider
retains exact evidence observations and can call the existing `ExtractionAgent`
when `ALPHA_GRAPH_EXTRACTION_ENABLED=true`. That option uses the configured
`extraction` role in `config/models.yaml`; a missing API key causes a safe job
failure naming the missing setting, without echoing a secret. No network or model
call is required for the default empty-evidence and fixture paths.

The extractor can only propose relationships. Exact quotes must pass the
existing validator, and the deterministic graph policy alone sets lifecycle,
strategy eligibility, confidence, exposure, and propagation weight. Evidence
with availability after the effective cutoff, or retrieval after the knowledge
cutoff, is excluded before proposal handling. An offline `FakeLLMClient` test
exercises the injectable composition path and verifies that a model-suggested
confidence of 1.0 cannot make a single-source edge strategy-eligible.

## Entity and visualization boundary

Every locked instrument has its own instrument node and an economic entity node.
If a locked `InstrumentRef` lacks an `entity_id`, the graph derives the stable
`entity:<instrument_id>` ID. Evidence mentions outside the locked universe may
be retained as `external_context` nodes. Stored snapshots preserve both node
types; the UI projection hides duplicate entity nodes and projects entity-level
economic relationships onto their linked locked instruments. External context
nodes remain visible. Coverage counts unique connected locked instruments,
eligible projected relationships, all projected relationships, and evidence
freshness computed from the recorded support time.

NetworkX is a runtime dependency for the bounded analysis adapter; durable graph
storage and API normalization do not depend on NetworkX algorithms.

## Verification and remaining runtime checks

Wave 3 focused tests, the full Python suite, Ruff, strict mypy, web tests, and the
web production build pass. The fake model confirms interface and policy behavior
but does not establish extraction quality. A separate bounded paid smoke test
then made exactly two Luna calls over official ASML/TSMC documents already stored
in the ignored local ledger. It produced one exact-quote-validated `ASML → TSM`
`equipment_dependency` proposal and one correct no-proposal result. Deterministic
policy assigned 0.669866 confidence but kept the relationship
strategy-ineligible because only one independent source supported it. No new
source pages were fetched during this smoke test.

The live PostgreSQL repository round-trip remains unverified without
`TEST_POSTGRES_DSN`, and the Compose services/migration have not been launched in
Docker in this environment. API durability and restart recovery are verified
with the durable job contracts and a newly constructed worker against the
in-memory test repositories. Production restart behavior still depends on the
PostgreSQL/Redis runtime being available and healthy.
