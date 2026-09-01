from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.adapters.base import SourceSnapshot
from alpha_workbench.agents.extraction import ExtractionAgent, FilingExtractionRequest
from alpha_workbench.extraction import (
    EvidenceProposalExtractor,
    EvidenceValidator,
    FilingSectionSelector,
)
from alpha_workbench.llm.models import FakeLLMClient


class FakeSecAdapter:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def discover(self, query: dict[str, object]) -> list[dict[str, object]]:
        del query
        return [{"source_url": "https://example.test/filing"}]

    def fetch(
        self, identifier: str, *, available_at: datetime | None = None
    ) -> SourceSnapshot:
        content_hash = "a" * 64
        (self.cache_dir / f"{content_hash}.html").write_text(
            "<p>TSMC supplies manufacturing capacity for NVIDIA products.</p>", encoding="utf-8"
        )
        now = datetime.now(UTC)
        return SourceSnapshot(
            source="fixture", source_url=identifier, retrieved_at=now, observed_at=now,
            available_at=available_at or now, content_sha256=content_hash, usage_note="fixture",
        )


def test_extraction_agent_composes_source_selection_and_validation(tmp_path: Path) -> None:
    response = {
        "source_entity_id": "TSM", "target_entity_id": "NVDA",
        "relationship_type": "manufacturing_dependency",
        "evidence_quote": "TSMC supplies manufacturing capacity for NVIDIA",
        "rationale": "fixture", "suggested_confidence": 0.8,
    }
    agent = ExtractionAgent(
        FakeSecAdapter(tmp_path), FilingSectionSelector(window_characters=100),
        EvidenceProposalExtractor(FakeLLMClient(response), {"TSM", "NVDA"}),
        EvidenceValidator({"TSM", "NVDA"}), tmp_path,
    )
    report = agent.run_filing(FilingExtractionRequest(cik="1", known_entities={"TSM", "NVDA"}))
    assert report.validations[0].verdict == "pass"
