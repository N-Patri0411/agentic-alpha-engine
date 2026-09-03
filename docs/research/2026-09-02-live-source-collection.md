# Live source-collection smoke run — 2026-09-02

## Purpose

Validate real provider behavior after local source credentials were configured.
This is an operational smoke run, not a historical research result and not a
claim of a relationship or alpha.

## Run result

The bounded whole-source command completed under run ID
`live-initial-source-2026-09-02-r3`. Its ignored local evidence ledger contains:

| Family | Result |
| --- | --- |
| Alpha Vantage daily market data | 6 completed calls, 100 daily OHLCV bars each (600 observations) |
| Tavily discovery | 8 completed focused queries, 5 results each (40 discovery observations) |
| SEC filings | NVIDIA 10-Q and TSM 6-K produced selected text evidence; AMD's current selected filing produced no ranked passage |
| SEC earnings fallback | no EX-99 earnings exhibit was found in the one-filing window used by this first run |
| Official IR/newsrooms | 3 successful and 5 failed source receipts with the initial catalog |

The first run exposed a boundedness issue: the earnings fallback expanded every
historical eligible SEC filing before limiting its work. It was stopped after
one valid observation and then corrected in commit `0895ca7`. The corrected
implementation limits the primary filings before inspecting exhibits and checks
at most four newest eligible filings for one earnings document.

## Concrete source examples returned

- NVIDIA's August 2026 10-Q included a selected passage about supply constraints,
  commitments to secure inventory/capacity, manufacturing and supply agreements,
  and expansion of its supplier base.
- TSM's September 2026 6-K was a cash-dividend adjustment notice. This confirms
  that the source collection is honest: a valid filing need not contain a
  relationship-bearing passage.
- SK hynix's official newsroom supplied current items about AI-memory and an
  Indiana fabrication facility. These are retained as official source evidence,
  not automatically treated as graph edges.
- Tavily returned lower-tier semiconductor supply-chain material from sources
  such as OECD, CSIS, academic publications, and the Turing Institute. Those
  records are discovery/corroboration only and cannot independently publish a
  graph edge.

## Official newsroom follow-up

The initial NVIDIA, TSM, Micron and GlobalFoundries URLs had become stale; UMC
also returned a 403 and GlobalFoundries timed out. Commit `5d3d87a` replaces the
stale URLs with current official landing pages and prevents `#fragment` links
from being stored as duplicate documents.

A direct post-fix probe reached content for NVIDIA, AMD, TSM, Samsung, and SK
hynix. Micron and UMC still return 403 to the scripted client and
GlobalFoundries timed out. These failures remain explicit receipts. The next
source-hardening slice should add reviewed official RSS/feed or documented
download fallbacks for those issuers; it must not attempt to evade site access
controls.

## Outcome

All initial source families now have real working adapter paths. Reliability is
not yet uniform across every official newsroom, which is expected with
third-party sites and is recorded rather than hidden. The evidence layer remains
safe to use for the next step: select retained text observations and send only
those to Luna for constrained relationship drafting.
