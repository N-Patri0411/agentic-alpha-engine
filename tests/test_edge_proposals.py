from alpha_workbench.extraction import (
    DocumentPassage,
    EdgeProposal,
    EvidenceProposalExtractor,
    EvidenceValidator,
    NoEdgeProposal,
)
from alpha_workbench.llm.models import FakeLLMClient


def _passage() -> DocumentPassage:
    return DocumentPassage(
        snapshot_sha256="a" * 64,
        source_url="https://example.test/filing",
        start_offset=0,
        end_offset=100,
        text="The company relies on TSMC for manufacturing advanced products.",
        matching_keywords=["manufactur"],
    )


def test_validator_accepts_exact_quote_and_known_entities() -> None:
    proposal = EdgeProposal(
        source_entity_id="TSM",
        target_entity_id="NVDA",
        relationship_type="manufacturing_dependency",
        evidence_quote="relies on TSMC for manufacturing",
        passage=_passage(),
        rationale="fixture",
        suggested_confidence=0.7,
    )
    report = EvidenceValidator({"TSM", "NVDA"}).validate(proposal)
    assert report.verdict == "pass"


def test_validator_rejects_unsourced_or_unknown_proposal() -> None:
    proposal = EdgeProposal(
        source_entity_id="UNKNOWN",
        target_entity_id="NVDA",
        relationship_type="manufacturing_dependency",
        evidence_quote="made up quotation",
        passage=_passage(),
        rationale="fixture",
        suggested_confidence=0.7,
    )
    report = EvidenceValidator({"TSM", "NVDA"}).validate(proposal)
    assert report.verdict == "fail"
    assert len(report.reasons) == 2


def test_extractor_represents_model_abstention_without_a_draft() -> None:
    result = EvidenceProposalExtractor(
        FakeLLMClient(
            {"source_entity_id": None, "target_entity_id": None, "reason": "not supported"}
        ),
        {"TSM", "NVDA"},
    ).extract(_passage())
    assert isinstance(result, NoEdgeProposal)
