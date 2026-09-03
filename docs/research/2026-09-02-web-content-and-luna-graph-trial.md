# Web content and Luna graph trial

## Purpose

Prove the path from an external discovery result to actual readable page content,
then through the two bounded Luna-backed agents into a scratch graph snapshot.
This is an engineering integration trial, not an investment claim and not a
promotion to the reviewed project graph.

## Run sequence

On 2026-09-02, a focused Tavily discovery query found official NVIDIA Newsroom
pages about NVIDIA's collaborations with SK hynix and Samsung. The controlled
web-content adapter then fetched only allow-listed HTTPS pages, cached their raw
responses locally, converted their visible narrative content to text, and
retained relationship-ranked passages which named two approved registry
entities. It did not treat Tavily's title or summary as the evidence itself.

The live trial used the following two configured model roles:

| Stage | Model role | What it did |
| --- | --- | --- |
| Extraction | `gpt-5.6-luna` | Converted retained, exact source passages into constrained relationship proposals. |
| Graph adjudication | `gpt-5.6-luna` | Reviewed the proposals against source-tier, alias, and bounded-update rules. |

The page collector returned six retained passages from four fetched candidates.
One PDF candidate was deliberately rejected because the current controlled
adapter accepts HTML or plain text only. The official NVIDIA material produced
an approved *trial* relationship:

```text
SK hynix -- manufacturing dependency --> NVIDIA
dependency strength: 0.70
substitutability:     0.50
confidence:           0.70
```

The trial snapshot also carried the two previously reviewed SEC relationships:

```text
TSMC -- manufacturing dependency --> NVIDIA
TSMC -- manufacturing dependency --> AMD
```

The local, ignored output is
`artifacts/live-agent-trials/live-luna-graph-2026-09-02-snapshot.json`.
It must not be copied into `data/graph_snapshots/` without review.

## What this validates

- Discovery is now followed by bounded retrieval of the public page's actual
  narrative text, not title/URL-only handling.
- Source material is stored as common `EvidenceObservation` records with URL,
  content hash, timing, exact retained span, source tier, and run provenance.
- Luna never fetches arbitrary pages. It receives only those recorded passages.
- The Extraction Agent and Graph Adjudicator can produce a graph decision in
  the existing typed A2A workflow.
- A graph snapshot remains immutable once written.

## Important limits and next hardening step

The fetched pages retain the `discovery` evidence tier even when the target is
an official site, because discovery initiated the intake. Therefore one page
cannot independently establish a durable edge; this trial used corroborating
passages and still wrote only an ignored scratch snapshot. It is deliberately
less authoritative than a directly catalogued official filing or IR feed.

The first receipt included navigation/header text in one saved quote. The page
parser now excludes header, navigation, footer, sidebar, and form content and
versions the derived observations, so future runs keep the narrative passage
that the agents actually reason about. A repeatable manual graph-workflow CLI
and a review screen are the next pieces needed before this can be a normal
nightly operation.
