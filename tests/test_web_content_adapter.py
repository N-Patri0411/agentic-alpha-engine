from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from alpha_workbench.adapters.web_content import WebFetchPolicy, WebPageContentAdapter
from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)

NOW = datetime(2026, 9, 2, 12, tzinfo=UTC)


def _candidate(url: str = "https://research.example.test/article") -> EvidenceObservation:
    return EvidenceObservation(
        idempotency_key="discovery-fixture",
        document=SourceDocument(
            source_kind="web_discovery",
            source_tier="discovery",
            source_adapter="fixture-discovery",
            source_url=url,
            content_sha256="a" * 64,
            issuer_entity_id="NVDA",
            observed_at=NOW,
            available_at=NOW,
            retrieved_at=NOW,
            usage_note="discovery fixture",
            title="NVIDIA and TSMC report",
        ),
        mentioned_entity_ids=("NVDA",),
        payload=TextEvidence(
            text="Discovery summary.",
            exact_quote="Discovery summary.",
            character_start=0,
            character_end=18,
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="discovery-run"
        ),
    )


def _adapter(tmp_path: Path, handler: httpx.MockTransport) -> WebPageContentAdapter:
    return WebPageContentAdapter(
        tmp_path / "web",
        WebFetchPolicy(policy_id="fixture", allowed_hosts=("research.example.test",)),
        client=httpx.Client(transport=handler),
        now=lambda: NOW,
    )


def test_web_content_adapter_fetches_full_page_and_ranks_exact_passages(tmp_path: Path) -> None:
    content = b"""
    <html><body><p>Introductory text.</p>
    <p>NVIDIA relies on TSMC manufacturing capacity for advanced GPU supply.
    The supply agreement covers leading products.</p></body></html>
    """
    adapter = _adapter(
        tmp_path, httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    )
    observations = adapter.collect(
        {
            "candidate": _candidate().model_dump(mode="json"),
            "entity_aliases": {"NVDA": ["NVIDIA"], "TSM": ["TSMC"]},
            "run_id": "content-run",
        }
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.mentioned_entity_ids == ("NVDA", "TSM")
    assert observation.payload.section == "fetched_discovery_passage"
    assert "NVIDIA relies on TSMC" in observation.payload.text
    assert observation.payload.exact_quote in observation.payload.text
    assert (tmp_path / "web" / f"{observation.document.content_sha256}.html").exists()


def test_web_content_adapter_rejects_unreviewed_hosts_and_redirects(tmp_path: Path) -> None:
    adapter = _adapter(
        tmp_path,
        httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "https://other.test/"})
        ),
    )
    query = {
        "candidate": _candidate().model_dump(mode="json"),
        "entity_aliases": {"NVDA": ["NVIDIA"], "TSM": ["TSMC"]},
    }
    with pytest.raises(ValueError, match="redirect target"):
        adapter.collect(query)
    query["candidate"] = _candidate("https://unreviewed.test/article").model_dump(mode="json")
    with pytest.raises(ValueError, match="allow-list"):
        adapter.collect(query)
