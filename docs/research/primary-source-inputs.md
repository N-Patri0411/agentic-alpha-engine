# Primary-source input adapters

The first primary-source adapters emit immutable `EvidenceObservation` records
only. They do not create a relationship, adjust a graph weight, or imply a
trading signal.

## SEC EDGAR

`SecFilingAdapter` collects the primary document for 10-K, 10-Q, 8-K, 20-F,
and 6-K filings. A bounded run can additionally retrieve EX-99-style exhibits
listed in that filing's EDGAR index; these commonly include an attached earnings
release. The filing date is used as a conservative availability timestamp.

Filings are public records, but EDGAR does not provide guaranteed intraday
availability timing through this adapter. Historical research must not assume
that a filing was usable before the recorded `available_at` timestamp.

## Official investor-relations sources

`OfficialInvestorRelationsAdapter` accepts only reviewed `CatalogSource` values
from the tracked source catalog. It supports RSS/Atom release summaries and
configured official HTML newsroom or investor-relations pages. Feed entries use
their published timestamp when supplied. A landing page usually has no reliable
publication timestamp, so it is explicitly timestamped at retrieval and must
not be treated as point-in-time historical evidence.

The initial catalog intentionally contains only official company and SEC URLs.
It is an allow-list, not a web crawler. Individual companies may redesign their
pages, publish JavaScript-only pages, remove archives, or provide no transcript.
Such collection failures should produce a run receipt error in the integrating
workflow; they must not be silently converted into evidence.

## Evidence boundary

Source adapters retain raw documents only in ignored local cache directories.
The ledger stores source URLs, hashes, timings, and bounded evidence text. The
later Extraction Agent may turn a source observation into a relationship draft;
the Graph Adjudicator decides whether any draft affects an immutable graph
snapshot.
