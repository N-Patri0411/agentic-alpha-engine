# Semiconductor Core 10 graph build — 2026-09-03

## Goal

Move beyond the earlier three-edge integration trial by collecting current public
material across the 10-company semiconductor registry, then run selected
pair-specific official evidence through Luna Extraction and Graph Adjudication.

## Live evidence collection

The source run `semiconductor-core-10-source-2026-09-03` recorded 853 local
evidence observations from live public sources:

| Family | Observations | Notes |
| --- | ---: | --- |
| Alpha Vantage | 800 | Daily bars for the eight tradeable registry entities; not used to create graph edges. |
| Tavily discovery | 36 | Candidate URLs only; used to find official pages. |
| Official IR | 16 | Public configured newsroom/IR pages. |
| SEC | 1 | One relationship-ranked current filing passage. |

Targeted discovery then located official company pages naming registered entity
pairs. The controlled content adapter retrieved those pages, removed webpage
chrome, kept exact text spans, and classified pages from tracked official hosts
as `official` evidence. It does not elevate arbitrary web sources.

## Bounded Luna result

The manual `build-graph-from-evidence` command selected at most five unseen,
pair-specific official passages. Luna Extraction proposed only two new
relationships that passed deterministic quote/entity validation and Graph
Adjudication:

| Relationship | Official evidence | Result |
| --- | --- | --- |
| GlobalFoundries → AMD | Extension of an AMD wafer-supply agreement | Approved manufacturing dependency |
| Micron → NVIDIA | HBM4 production designed for NVIDIA Vera Rubin | Approved manufacturing dependency |
| TSMC → ASML | TSMC statement that it works with ASML on capability | No proposal; retained as a negative result |
| GlobalFoundries ↔ Samsung | Generic collaboration announcement | No proposal |
| NVIDIA ↔ Samsung | Generic AI-factory announcement | No proposal |

The final local snapshot
`artifacts/semiconductor-core-10-2026-09-03.json` has five edges: the original
reviewed TSMC-to-NVIDIA and TSMC-to-AMD edges, the prior trial SK hynix-to-NVIDIA
edge, plus the two new relationships above. The visible graph has 10 nodes and
six connected companies. ASML, Samsung, Applied Materials, and UMC remain
isolated because this run did not establish an approved relationship for them.

## Interpretation

This is a real evidence-backed demonstration graph, not a complete industry
map. Empty nodes are a valuable result: the system is refusing to turn vague
corporate collaboration language into dependency claims. The next expansion
should target direct equipment/customer disclosures for ASML, Applied Materials,
Samsung, and UMC, then compare each new graph snapshot against this baseline.
