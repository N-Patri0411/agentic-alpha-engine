# Wave 4 Strategy DSL and Alpha Generator Contract

## Scope and assumptions

The existing expression parser remains the only formula language. Candidate
strings are parsed into a bounded AST and never passed to `eval`, compiled, or
imported as Python. Luna (or another configured model) proposes typed JSON;
catalog, cadence, operator-axis, lookback, deduplication, and trial-limit rules
are deterministic application checks.

`GeneratorFeatureRef` is the narrow alpha-generator input shape. It is named
separately from the versioned `alpha_workbench.features.FeatureDefinition`
contract so the two packages do not define competing public feature records.
At the service boundary, callers provide name, numeric type, cadence, axis
support, availability, source IDs, and optional feature/dataset/graph pins.
Feature-frame materialization remains responsible for retaining row-level
`observed_at` and `available_at` and for dropping values that were unavailable
at the run's `as_of_time`.

## Stable contracts

- `SignalSpec` is frozen and carries source and canonical formula, strategy
  cadence, typed feature references, provenance/rationale, as-of time, graph
  pin, and portfolio/risk/validation settings.
- `SignalSpec.to_strategy_spec(...)` adapts to the existing immutable product
  `StrategySpec`; dataset version IDs are derived from referenced features and
  graph version ID is passed through.
- `canonicalize_expression` removes numeric-format and whitespace variation
  and sorts commutative `Add`/`Mul` operands. It deliberately does not apply
  algebraic rewrites beyond these cases.
- Windows are counts of observations at the selected strategy cadence. The
  evaluator must receive a frame aligned to that cadence; it does not infer or
  resample source data.
- Cross-sectional operators (`Rank`, `ZScore`) require the referenced feature
  to support the cross-section axis. Rolling and lag operators require
  time-series support. Lookbacks must be integer constants from 1 to 252.
- Frequency matching is strict by default. A quarterly feature may be used in
  a monthly signal only with `feature_frequency_policy=
  "quarterly_release_to_monthly"`, a timezone-aware run `as_of_time`, and an
  explicit feature `available_at` no later than that cutoff. This is a
  permission to consume a release-aligned monthly panel, not an instruction to
  forward-fill or resample; the frame builder must perform and record that
  alignment under point-in-time rules.
- `AlphaGeneratorService.generate(payload, experiment_id=..., trial_limit=...)`
  is the router-facing seam. Inject a durable implementation of `TrialLedger`
  for cross-process experiment-wide accounting. The default in-memory ledger
  provides deterministic local behavior only. Duplicate canonical formulas
  are not counted twice; novel formulas beyond the limit are rejected, and the
  result reports `experiment_id`, `trial_count`, and `trial_limit`.
- `AdvancedPythonExtensionRegistry` is disabled by default. Enabling requires
  host code to explicitly register an inspectable callable by a public name and
  exact source SHA-256. Model responses cannot define/import code or select an
  unregistered callable. The extension registry is a separate trust boundary
  and is not part of the default formula evaluator.

## Verification boundaries

The generator tests check syntax safety, point-in-time and cadence rejection,
operator axes, quarterly release policy, pins, canonical deduplication,
candidate-batch bounds, trial accounting, and extension defaults. These are
software contract checks; they do not establish signal quality or strategy
performance. Durable trial storage and UI/API exposure are integration work.
