# Live SEC Extraction Trial — 2026-09-01

## Purpose

Verify the Extraction Agent against public filings and Luna using actual source
text, rather than treating test fixtures as research evidence. All outputs are
drafts only: they were not published into the supply-chain graph.

## Runs

| Issuer / form | Filing date | Result | Deterministic evidence check |
| --- | --- | --- | --- |
| NVIDIA / 10-K | 2026-02-25 | Draft `TSM -> NVDA`, `manufacturing_dependency` | pass |
| AMD / 10-K | 2026-02-04 | Draft `TSM -> AMD`, `manufacturing_dependency` | pass |
| TSMC / 20-F | 2026-04-16 | No proposal | not applicable |

NVIDIA's selected passage expressly identifies TSMC and Samsung as foundries
used to produce its semiconductor wafers. AMD's selected passage expressly
states reliance on TSMC for wafers used in its microprocessor and GPU products
at nodes of 7 nm or smaller. The TSMC passage discussed an ecosystem of fabs
and suppliers but did not identify an approved counterpart; retaining no edge
is the correct result.

## Source receipts

- NVIDIA: accession `0001045810-26-000021`, snapshot
  `73d81f5a111abcf72426c840871e76f5f5edc9631f436d495a86b6f87306d58b`.
- AMD: accession `0000002488-26-000018`, snapshot
  `247b08e661e15f3c3a18a77ea40c0fa8702d23c4b05e2d5303e305840c45b111`.
- TSMC: accession `0001628280-26-025362`, snapshot
  `c3ebd05cd8fb383f53fc21a0ac497ee12cf908b709c380f9bec4f39c4916647b`.

The raw SEC documents are ignored local cache files. The SEC source URLs,
filing dates, snapshot hashes, selected passage, model draft, and validator
receipt are printed by `extract-sec` for later immutable-run storage.

## What changed after the first failed live trial

The initial selector flattened hidden Inline-XBRL taxonomy metadata and chose
that metadata because it contained words such as `manufacturing`. It now
excludes non-narrative XBRL sections and ranks passages containing relationship
language such as "we rely on" or "we utilize". The agent also receives the
approved issuer entity ID, resolving a filing's first-person references (for
example, NVIDIA's "we") without inventing an entity.

## Remaining limitations

- The entity IDs and aliases are supplied manually for this trial; the planned
  domain entity registry will own that mapping.
- One model call yields at most one draft. Batch extraction and the human review
  inbox are not built yet.
- A validator proves only provenance, entity membership, and exact quoting. It
  does not establish economic materiality, edge strength, or investability.

## 2026-09-02 end-to-end A2A trial

Two bounded, live trials used one ranked passage each from the current public
NVIDIA and AMD 10-K filings. Each passed through the durable
Extraction-to-Graph A2A workflow with Luna configured for both agents:

| Issuer | Extraction result | Graph decision | Trial artifact |
| --- | --- | --- | --- |
| NVIDIA | `TSM -> NVDA`, manufacturing dependency | `approve_edge` | immutable scratch snapshot |
| AMD | `TSM -> AMD`, manufacturing dependency | `approve_edge` | immutable scratch snapshot |

The trial artifacts and message databases remain ignored local files. Neither
snapshot was promoted into the reviewed project graph. Both relationships were
already present in the baseline snapshot, so this run validates source
collection, message hand-off, model output, and graph publication—not a new
topology claim or a production weight update.

The first attempt correctly failed closed: the Graph model used the common
aliases `approve` and scalar `state_delta` rather than the strict contract. The
adjudicator now accepts only those documented aliases, maps a scalar delta only
to dependency strength, and still rejects all unknown actions or shapes. This
compatibility rule has a regression test.
