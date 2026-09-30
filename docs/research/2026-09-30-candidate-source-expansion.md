# Candidate graph source expansion — 2026-09-30

Candidate graph formation now consumes every text observation in the evidence
ledger, including lower-tier web-discovery summaries. Market bars and
structured filing facts remain excluded from relationship extraction. Source
tier, source kind, adapter, observation ID, and whether the text is a full
document or discovery summary are carried through the passage, extracted
relationship, and candidate edge.

This is intentionally a recall-oriented candidate layer. Discovery titles and
URLs are locator metadata, not relationship evidence. Discovery-summary
evidence enters normal adjudication with lower reliability/freshness weighting
and visible provenance; there is no hard minimum corroboration requirement.
Promotion remains governed by the model decision and graph policy. The expanded
input makes competition and collaboration candidates between known registry
entities visible without changing the reviewed graph.

The broad-source live trial subsequently produced one candidate edge, linking
Tata Electronics to ASML. That limited edge coverage is a reminder that broad
discovery alone does not connect the full registry; targeted documents are
needed to investigate remaining isolated anchors and relationship types.
