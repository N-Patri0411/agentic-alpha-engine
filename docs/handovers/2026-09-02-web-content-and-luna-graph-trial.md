# Handover — web content and Luna graph trial

The controlled web-content adapter now turns a reviewed Tavily discovery result
into content-bearing evidence. It is not a crawler: it accepts only a prior
discovery record, retrieves only tracked allow-listed HTTPS hosts, constrains
redirects and response size, caches raw responses locally, and records exact
ranked spans in the ignored DuckDB ledger.

The live NVIDIA newsroom trial used Luna for both Extraction and Graph
Adjudication. It created an ignored scratch snapshot with a `Hynix -> NVDA`
manufacturing-dependency edge. The result and its limitations are documented in
`docs/research/2026-09-02-web-content-and-luna-graph-trial.md`.

Do not promote the scratch artifact, its raw cache, the ledger, or any keys to
Git. Next work should package the bounded extraction-to-adjudication workflow
as a manual CLI, then add source-tier promotion and review UI before enabling a
scheduled graph publication.
