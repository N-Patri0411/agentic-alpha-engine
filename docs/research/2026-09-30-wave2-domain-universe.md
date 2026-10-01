# Wave 2 Domain and Universe Slice

## Scope

The Domain and Universe backend turns a domain description into a typed concept
set, gathers instruments through the provider-neutral discovery and identifier
mapping contracts, scores candidate liquidity and history coverage, and returns
an explainable diversified basket for review. The deterministic planner works
offline from frozen candidates. Provider-backed discovery uses current global
search where the configured adapter supports it.

## Selection method

- Domain concept expansion uses a small local synonym catalog. Unknown domains
  remain typed as their normalized phrase instead of being guessed by a model.
- A canonical FIGI and exchange are required for recommendation eligibility.
  Instruments without a canonical mapping remain visible as rejected entries.
- Relevance is provider-query match quality on a 0–1 scale; values below 0.35
  are rejected. Liquidity is a log-scaled mean of daily close times volume,
  converted to USD with point-in-time FX where needed. Coverage uses returned
  historical observations divided by the requested count.
- Total score weights relevance 50%, liquidity 25%, and coverage 25%. Selection
  applies bounded sub-industry and regional diversity bonuses (0.10 and 0.04 per
  repeated group). API scores are returned as rounded percentages.
- Provider resolution results retain their exchange. Multiple listings for one
  named company resolve by provider resolution rank, FIGI presence, then stable
  canonical identifier order. Replacements are limited to eligible alternatives
  and each user-removed instrument stays excluded from that plan.
- Current plans with a server-generated timestamp permit records retrieved during
  that run, filter them against the actual completion time, and then stamp the
  finalized selection time. An explicit current cutoff and all point-in-time
  requests remain strict. Point-in-time planning is rejected before discovery
  unless a configured discovery provider explicitly guarantees it.

## Frozen acceptance fixture

`tests/fixtures/domain/semiconductor_manufacturing_candidates.json` is synthetic
test data, not a market-data source. It covers ten global recommendations,
canonical FIGI/exchange resolution, a deliberately ambiguous ticker, an
unavailable listing, a low-relevance rejection, and replacement alternatives.
It is suitable for software determinism tests only and must not be treated as a
validated investment universe.

## Integration limits

The current provider contracts expose discovery and history but not a normalized
industry taxonomy or verified active-from dates for every exchange listing.
Sub-industry labels therefore come from the deterministic concept mapping, and
providers without point-in-time guarantees cannot supply point-in-time membership
on their own. Universe persistence now has its own typed boundary. Locking writes
the UniverseSpec and DomainWorkspace atomically in PostgreSQL and validates both
records before publishing either in memory. A typed universe-read route supports
reload after a process restart.
