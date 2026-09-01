"""Manual, one-passage live trial of the SEC-to-Luna extraction path."""

from __future__ import annotations

import json
from pathlib import Path

from alpha_workbench.adapters import SecFilingAdapter
from alpha_workbench.extraction import EvidenceProposalExtractor, FilingSectionSelector
from alpha_workbench.llm.models import create_llm, load_model_config


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    adapter = SecFilingAdapter(root / "data" / "cache" / "sec")
    filings = adapter.discover({"cik": "1045810", "forms": ["10-K"]})
    if not filings:
        raise RuntimeError("no selected filing was returned by SEC")
    snapshot = adapter.fetch(str(filings[0]["source_url"]))
    cached = root / "data" / "cache" / "sec" / f"{snapshot.content_sha256}.html"
    passages = FilingSectionSelector().select(cached, snapshot, max_passages=1)
    if not passages:
        raise RuntimeError("no evidence passage was selected from the filing")
    model = create_llm(load_model_config(root / "config" / "models.yaml", "extraction"))
    proposal = EvidenceProposalExtractor(
        model, {"NVDA", "TSM", "AMD", "ASML", "MSFT"}
    ).extract(passages[0])
    print(json.dumps(proposal.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
