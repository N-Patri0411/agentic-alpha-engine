# Autonomous temporal graph pipeline policy

## Scope

The graph pipeline consumes a locked `UniverseSpec`, immutable evidence
observations, validated extraction proposals, and optional semantic
assessments. It does not collect evidence, call a model, access the network, or
write graph files. Callers inject the temporal graph repository. Bootstrap,
nightly, and event-triggered request constructors are pure; publication is
performed only through the repository contract.

The locked universe supplies the allowed entity and instrument identities.
Instrument IDs, symbols, provider symbols, and optional caller aliases resolve
to canonical entity IDs. Discovery observations can contribute facts when
resolved, but only corroborated and eligible edge states are strategy inputs.

## Publication policy

Semantic adjudication may label a statement as support, contradiction, or
retirement. The deterministic policy owns source reliability, corroboration,
confidence, economic exposure, propagation, eligibility, weakening, and
retirement. It requires two independent source hosts and confidence of at least
0.50 for strategy eligibility. Independent source confidence is combined as
`1 - product(1 - source_quality)`. Evidence quality uses fixed source-tier
reliability and freshness half-lives; discovery evidence decays faster.
Contradictions above a 30% share require review and set economic exposure to
zero. Semantic assessments never provide numerical graph weights.

Nightly maintenance applies exponential decay and retires an edge after four
180-day half-lives without support. Event updates evaluate only relationships
named by the event observations or validated proposals. Snapshots remain full
and immutable; changed logical edges close their prior knowledge interval and
append a new state. Unaffected edge rows are copied unchanged.

Observations with `available_at` later than `as_of_time` are excluded. Request
fingerprints and deterministic snapshot IDs make exact replays no-ops; reusing
an explicit request ID for different graph content is rejected.

## Limits and validation

The current source reliability values and thresholds are conservative starting
policy values, not empirically calibrated likelihoods. A semantic assessment
must come from an already authorized classifier or deterministic rule, and its
quality still depends on source evidence. This pipeline intentionally does not
infer relationship semantics from arbitrary text by itself. It does not
replace out-of-sample validation of any downstream strategy.

The pipeline preserves bitemporal snapshots so historical effective and
knowledge-time views can be replayed. Repository implementations must retain
closed edge-state versions and enforce append-only publication.
