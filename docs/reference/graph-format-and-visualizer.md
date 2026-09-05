# Graph format and visualizer

## What the graph is

The graph is not stored as a NetworkX pickle or an opaque database. Its durable
format is two readable, versioned JSON files:

```text
data/entities/semiconductor_v1.json       # nodes: company identities
data/graph_snapshots/<snapshot>.json      # approved, dated relationships
```

The entity registry currently names ten semiconductor companies: TSMC, NVIDIA,
AMD, Samsung Electronics, SK hynix, Micron, GlobalFoundries, UMC, ASML, and
Applied Materials. A company can appear even when it has no approved
relationship yet. That is useful: it shows what still needs evidence rather
than silently pretending the company does not exist.

Each relationship in a graph snapshot is a custom, Pydantic-validated record.
It includes the direction, relationship type, dependency strength,
substitutability, confidence, time range, exact source evidence, review receipt,
and a checksum over the full edge list. The checksum makes later alteration of
a supposedly immutable snapshot detectable.

For example, a simplified relationship is:

```json
{
  "upstream_entity_id": "TSM",
  "downstream_entity_id": "NVDA",
  "relationship_type": "manufacturing_dependency",
  "dependency_strength": 0.75,
  "substitutability": 0.35,
  "confidence": 0.90,
  "evidence": {"source_url": "...", "evidence_quote": "..."}
}
```

The JSON contract is the source of truth. NetworkX is used only to lay it out
for viewing; it never makes graph decisions or writes graph snapshots.

## Candidate evidence graph versus reviewed scenario graph

The reviewed snapshot deliberately remains strict: it contains only approved,
effective-dated relationships whose state is safe for deterministic scenario
replay. It is not a claim that these are the only relationships in the real
industry.

Before that decision, the extraction system can create a separate **candidate
evidence graph**. It starts with the ten approved semiconductor anchors and may
add a newly named company, such as Microsoft, Apple, or HP, as a candidate node
when a source directly connects it to an anchor. This is capped at one hop:
Microsoft can be connected to NVIDIA or AMD, but a Microsoft-to-Apple claim is
not used to expand the graph further. That makes the graph useful for discovery
without turning one vague source into an unbounded crawl.

Candidate relationships retain their exact quote, source URL, availability
time, type, rationale, and suggested confidence. They are never automatically
scored by `RippleRiskScorer`, written into a reviewed snapshot, or used as a
trading input. The Graph Adjudicator must later validate and promote a candidate
under rules specific to its relationship type.

## Create a visual view

After running `setup.cmd` or installing the requirements, create an HTML graph
from a reviewed snapshot:

```powershell
.venv\Scripts\python.exe -m alpha_workbench visualize-graph `
  --snapshot data/graph_snapshots/semiconductor-sec-reviewed-v1.json `
  --output reports/semiconductor-graph.html
```

The output is a local HTML file. Blue circles are tradeable instruments; green
circles are relevant but non-tradeable companies. Dim nodes are intentionally
isolated because the system has not approved an edge yet. Edge arrows show the
supply/cause direction. Click an arrow or its table row to inspect dependency
strength, substitutability, confidence, freshness, stress values, evidence
support, exact source quote, and review receipt.

To view the local Luna trial graph used in the latest experiment, run:

```powershell
.venv\Scripts\python.exe -m alpha_workbench visualize-graph `
  --snapshot artifacts/live-agent-trials/live-luna-graph-2026-09-02-snapshot.json `
  --output reports/live-luna-graph.html
```

That trial includes the proposed SK hynix to NVIDIA relationship. It is a local
scratch artifact, not a replacement for the tracked reviewed snapshot.

## Build a bounded graph from collected evidence

The manual graph-build command connects the real Extraction and Graph
Adjudication agents. It selects a small number of unseen, official,
pair-specific passages, records typed A2A messages, and writes a new local
snapshot without overwriting its input:

```powershell
.venv\Scripts\python.exe -m alpha_workbench build-graph-from-evidence `
  --evidence-run semiconductor-core-relationship-content-v3-2026-09-03 `
  --current-snapshot artifacts/live-agent-trials/live-luna-graph-2026-09-02-snapshot.json `
  --snapshot-id semiconductor-core-demo `
  --snapshot-output artifacts/semiconductor-core-demo.json `
  --run-id semiconductor-core-demo `
  --max-observations 5
```

The five-passage limit is intentional: it keeps the manual Luna budget and the
reviewable evidence scope predictable. A rejected passage remains a useful
negative result; the command does not create an edge simply to make a graph look
more complete.

## Discover bounded external candidates

To inspect direct relationships that mention a company outside the initial ten,
run the separate candidate-discovery command on evidence that has already been
collected. It uses the model configured for the Extraction role (currently Luna)
but accepts only primary/official full-text observations, never search-result
summaries or market bars.

```powershell
.venv\Scripts\python.exe -m alpha_workbench discover-candidate-graph `
  --evidence-run semiconductor-core-relationship-content-v3-2026-09-03 `
  --run-id semiconductor-candidate-demo `
  --output artifacts/semiconductor-candidate-demo.json `
  --max-observations 5
```

The output belongs under ignored `artifacts/`. It is a review artifact: it can
show a newly named first-hop node, its direct source quote, and a candidate
relationship type. It does not publish a snapshot, replace the ten-anchor
registry, or run a scenario. A later Graph Adjudicator policy must decide whether
each candidate has sufficient evidence to promote.
