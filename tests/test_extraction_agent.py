from datetime import UTC, datetime
from pathlib import Path

import pytest

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


class RecordingLLM(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__({"source_entity_id": None, "target_entity_id": None, "reason": "fixture"})
        self.user = ""

    def complete_json(self, *, system: str, user: str) -> dict[str, object]:
        self.user = user
        return super().complete_json(system=system, user=user)


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
    report = agent.run_filing(
        FilingExtractionRequest(
            cik="1", issuer_entity_id="NVDA", known_entities={"TSM", "NVDA"}
        )
    )
    assert report.validations[0].verdict == "pass"


def test_extraction_agent_supplies_issuer_context_to_the_model(tmp_path: Path) -> None:
    llm = RecordingLLM()
    agent = ExtractionAgent(
        FakeSecAdapter(tmp_path), FilingSectionSelector(window_characters=100),
        EvidenceProposalExtractor(llm, {"TSM", "NVDA"}),
        EvidenceValidator({"TSM", "NVDA"}), tmp_path,
    )
    agent.run_filing(
        FilingExtractionRequest(
            cik="1", issuer_entity_id="NVDA", known_entities={"TSM", "NVDA"}
        )
    )
    assert "Filing issuer entity ID: NVDA" in llm.user


def test_incomplete_model_edge_is_rejected_before_validation(tmp_path: Path) -> None:
    agent = ExtractionAgent(
        FakeSecAdapter(tmp_path), FilingSectionSelector(window_characters=100),
        EvidenceProposalExtractor(
            FakeLLMClient({"source_entity_id": "NVDA", "target_entity_id": "TSM"}),
            {"TSM", "NVDA"},
        ),
        EvidenceValidator({"TSM", "NVDA"}), tmp_path,
    )
    with pytest.raises(ValueError, match="failed contract validation"):
        agent.run_filing(
            FilingExtractionRequest(
                cik="1", issuer_entity_id="NVDA", known_entities={"TSM", "NVDA"}
            )
        )


def test_extraction_agent_accepts_common_text_observations(tmp_path: Path) -> None:
    from alpha_workbench.agents.extraction import ObservationExtractionRequest
    from alpha_workbench.evidence import (
        EvidenceObservation,
        ExtractionProvenance,
        SourceDocument,
        TextEvidence,
    )

    text = "TSMC supplies manufacturing capacity for NVIDIA products."
    observation = EvidenceObservation(
        idempotency_key="fixture-observation",
        document=SourceDocument(
            source_kind="investor_relations", source_tier="official", source_adapter="fixture",
            source_url="https://example.test/evidence", content_sha256="b" * 64,
            issuer_entity_id="NVDA", observed_at=datetime.now(UTC), available_at=datetime.now(UTC),
            retrieved_at=datetime.now(UTC), usage_note="fixture",
        ),
        mentioned_entity_ids=("NVDA", "TSM"),
        payload=TextEvidence(
            text=text, exact_quote=text, character_start=0, character_end=len(text)
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="fixture-run"
        ),
    )
    response = {
        "source_entity_id": "TSM", "target_entity_id": "NVDA",
        "relationship_type": "manufacturing_dependency", "evidence_quote": text,
        "rationale": "fixture", "suggested_confidence": 0.8,
    }
    agent = ExtractionAgent(
        FakeSecAdapter(tmp_path), FilingSectionSelector(window_characters=100),
        EvidenceProposalExtractor(FakeLLMClient(response), {"TSM", "NVDA"}),
        EvidenceValidator({"TSM", "NVDA"}), tmp_path,
    )
    report = agent.run_observations(
        ObservationExtractionRequest(observations=[observation], known_entities={"TSM", "NVDA"})
    )
    assert report.validations[0].verdict == "pass"
