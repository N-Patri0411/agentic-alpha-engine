# Historical graph-and-price panel — 2026-09-30

## Purpose

The historical panel is the smallest reproducible bridge between changing graph
state and later market outcomes. It is an evaluation input, not a claim that a
graph score predicts returns. The panel makes it possible to compare:

- an **evolving** graph, selecting the latest immutable snapshot available at
  each market bar; and
- a **static** graph, reusing one explicitly selected snapshot as a baseline.

The implementation is in `src/alpha_workbench/historical_panel.py`. Each output
row retains the price close, graph score, graph snapshot ID, graph availability,
market-bar availability, and a `forward_return` label. The label is calculated
after the score and is explicitly an outcome; it must not be passed into graph
construction or factor generation.

## Timing rule

For a price bar available at time `t`, the evolving panel chooses the latest
snapshot whose conservative availability time is no later than `t`. Snapshot
availability is the maximum of its creation time, evidence filing times, and
review times. Price rows published after the panel's `as_of_time` are excluded.
If no eligible graph snapshot exists for a price bar, that row is excluded and
the receipt counts it. This makes missing history visible instead of filling it
with a later graph version.

## Current fixture result

The frozen tests create a second snapshot with a changed TSMC-to-NVIDIA
dependency weight and five price dates. The panel proves that the first dates
use snapshot v1, dates after the v2 availability use v2, future price rows are
excluded, and the static/evolving comparison exposes the score delta. The tests
are an engineering check only; they do not establish a useful signal.

## Data still required for an honest validation

The tracked graph currently has a short, reviewed history and the local market
ledger is not synchronized between laptops. To run a meaningful comparison we
need:

1. Immutable graph snapshots at documented event dates, including changes in
   dependency strength, substitutability, capacity stress, and relationship
   additions/retirements. Every update needs evidence availability and an
   effective date.
2. Several years of daily adjusted or split-aware prices for the same tradeable
   universe, with source-specific availability timestamps and corporate-action
   treatment. A single current quote endpoint is not point-in-time history.
3. A documented data license. Alpha Vantage is acceptable for private
   development smoke tests, but its free feed should not be treated as a
   production-grade point-in-time dataset or redistributed by this project.
   Production research requires a provider whose historical terms permit the
   intended use and whose revisions/corporate actions are recorded.
4. Enough observations after each snapshot to form forward labels and rolling
   unseen evaluation windows. The panel does not manufacture labels when the
   next bar is missing.

The next acquisition step is to preserve a small, licensed/user-owned price
fixture with at least 40 aligned dates for the initial semiconductor registry,
then add reviewed graph snapshots around documented events. Only after that
should the rolling walk-forward evaluator and Gatekeeper acceptance thresholds
be used to discuss signal quality.
