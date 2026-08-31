# Semiconductor Domain Mapping Plan

## Goal

Build a small, high-confidence map of the global semiconductor ecosystem that is useful for research scenarios. This is not an attempt to map every company or every commercial relationship.

The first mapped slice will contain approximately 25 entities and at least 40 evidence-backed relationships. Every relationship must be dated, typed, and supported by a source that another contributor can inspect.

## Scope

Start with the AI-compute supply chain, because it connects a manageable set of equipment makers, foundries, chip designers, advanced packaging firms, cloud providers, and manufacturing-dependent customers.

The first entity categories are:

| Category | Purpose in the map | Example entities to investigate |
|---|---|---|
| Lithography / equipment | Bottlenecks in manufacturing capacity | ASML, Applied Materials, Lam Research |
| Foundries | Manufacture chips designed by other firms | TSMC, GlobalFoundries, Samsung Electronics |
| Chip designers | Design GPUs, CPUs, mobile chips, or accelerators | Nvidia, AMD, Qualcomm, Broadcom |
| Memory / materials | Provide important manufacturing inputs | Micron, SK hynix, Entegris |
| Packaging / testing | Assemble and validate finished chips | Amkor, ASE Technology |
| Cloud / large customers | Consume AI hardware at scale | Microsoft, Alphabet, Meta, Amazon |

## Relationship taxonomy

Do not force every relationship into a supplier-to-customer edge. Store its type and apply scenario behavior only when that behavior is explicitly defined.

| Type | Direction | First scenario behavior |
|---|---|---|
| `manufacturing_dependency` | supplier to customer | Propagate disruption exposure downstream. |
| `equipment_dependency` | equipment maker to manufacturer | Propagate capacity constraint downstream. |
| `packaging_dependency` | packaging provider to customer | Propagate disruption exposure downstream. |
| `customer_concentration` | supplier to major customer | Record exposure; do not infer a generic shock effect yet. |
| `competitive_substitution` | competitor to competitor | Record separately; no propagation until a tested benefit/harm rule exists. |
| `ip_or_license` | licensor to licensee | Record separately; no propagation in the first scenario engine. |
| `geographic_or_regulatory` | event to affected entity | Add only after an event taxonomy exists. |

## Data record design

### Entity record

Each entity needs a stable internal ID, legal name, ticker or trading instrument where applicable, category, headquarters/operating geography, aliases, and an active date range.

### Relationship record

Every edge must contain:

```text
source, target, relationship_type, effective_from, effective_to,
dependency_strength, substitutability, confidence,
source_url, source_document_date, evidence_note, reviewer_status
```

`dependency_strength`, `substitutability`, and `confidence` are research assumptions. They require a short evidence note explaining why the value was chosen. Unknown values remain unknown; do not invent precision.

## Evidence policy

Use primary sources first:

1. SEC 10-K, 10-Q, 20-F, and 6-K filings.
2. Company annual reports, investor presentations, and official product disclosures.
3. Official government or regulatory notices for geopolitical restrictions.

SEC's public filing APIs provide company submission history and XBRL facts without API-key authentication, subject to its access rules. The filing fetcher will preserve the accession number, filing date, retrieval time, and source URL. See the [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Do not add an edge merely because it is common knowledge or appears in an unsourced chart. Put uncertain candidate relationships in a review queue rather than the scenario engine.

## Build order

1. Add `entities.csv`, aliases, and a schema validator.
2. Extend edge records with taxonomy, evidence notes, review status, and relationship-specific scenario eligibility.
3. Populate a first 10-entity, 15-edge reviewed core around ASML, TSMC, Nvidia, AMD, and selected downstream users.
4. Add fixture tests for schema validation, dated-edge filtering, and non-propagating relationship types.
5. Expand to the 25-entity, 40-edge map only after a source-review pass.
6. Create a small catalogue of documented historical disruptions to validate scenario paths before attempting graph-machine-learning work.

## Definition of done

The domain-map milestone is complete when:

- Each included relationship has source evidence and a visible review status.
- The engine propagates only relation types with explicitly defined behavior.
- A dated scenario produces a deterministic, explainable path report.
- At least three historical case studies can be replayed without using future evidence.
- The documentation names assumptions and gaps instead of presenting the graph as ground truth.
