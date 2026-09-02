from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.a2a import DuckDBMessageBus
from alpha_workbench.adapters import SecFilingAdapter
from alpha_workbench.agents.extraction import ExtractionAgent
from alpha_workbench.agents.extraction_graph_workflow import ExtractionGraphWorkflow
from alpha_workbench.agents.graph_adjudicator import GraphAdjudicatorAgent
from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.extraction import (
    EvidenceProposalExtractor,
    EvidenceValidator,
    FilingSectionSelector,
)
from alpha_workbench.graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot
from alpha_workbench.llm.models import FakeLLMClient

REGISTRY = Path("data/entities/semiconductor_v1.json")
SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
AT = datetime(2026, 5, 1, tzinfo=UTC)


def _observation() -> EvidenceObservation:
    text = "NVIDIA relies on TSMC to manufacture advanced GPU products."
    return EvidenceObservation(
        idempotency_key="workflow-observation",
        document=SourceDocument(
            source_kind="sec_filing",
            source_tier="primary",
            source_adapter="fixture",
            source_url="https://example.test/workflow",
            content_sha256="d" * 64,
            issuer_entity_id="NVDA",
            observed_at=AT,
            available_at=AT,
            retrieved_at=AT,
            usage_note="workflow fixture",
        ),
        mentioned_entity_ids=("NVDA",),
        payload=TextEvidence(
            text=text, exact_quote=text, character_start=0, character_end=len(text)
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="workflow"
        ),
    )


def test_validated_extraction_message_reaches_graph_adjudication(tmp_path: Path) -> None:
    observation = _observation()
    extraction = ExtractionAgent(
        SecFilingAdapter(tmp_path / "cache", user_agent="Test test@example.com"),
        FilingSectionSelector(),
        EvidenceProposalExtractor(
            FakeLLMClient(
                {
                    "source_entity_id": "TSM",
                    "target_entity_id": "NVDA",
                    "relationship_type": "manufacturing_dependency",
                    "evidence_quote": "NVIDIA relies on TSMC to manufacture advanced GPU products.",
                    "rationale": "The passage explicitly identifies the manufacturer.",
                    "suggested_confidence": 0.8,
                }
            ),
            {"TSM", "NVDA"},
        ),
        EvidenceValidator({"TSM", "NVDA"}),
        tmp_path / "cache",
    )
    registry = EntityRegistry.from_json(REGISTRY)
    adjudicator = GraphAdjudicatorAgent(
        FakeLLMClient(
            {
                "action": "update_state",
                "upstream_entity_id": "TSM",
                "downstream_entity_id": "NVDA",
                "relationship_type": "manufacturing_dependency",
                "supporting_observation_ids": [str(observation.observation_id)],
                "rationale": "The validated passage confirms the active dependency.",
            }
        ),
        registry,
        GraphPublisher(registry),
    )
    bus = DuckDBMessageBus(tmp_path / "messages.duckdb")
    workflow = ExtractionGraphWorkflow(bus, extraction, adjudicator)

    workflow.enqueue_extraction(
        trace_id="trace-1",
        run_id="run-1",
        observations=[observation],
        known_entities={"TSM", "NVDA"},
        as_of_time=AT,
    )
    extraction_message = bus.inbox("extraction")[0]
    graph_message = workflow.process_extraction(extraction_message)

    assert graph_message is not None
    assert graph_message.recipient == "graph_adjudicator"
    assert bus.inbox("extraction") == []
    report = workflow.process_graph(
        graph_message,
        current_snapshot=GraphSnapshot.from_json(SNAPSHOT),
        next_snapshot_id="workflow-snapshot",
        snapshot_path=tmp_path / "workflow-snapshot.json",
    )

    assert report.published_snapshot_id == "workflow-snapshot"
    result_message = bus.inbox("orchestrator")[0]
    assert result_message.sender == "graph_adjudicator"
    assert result_message.artifact_references[0].id == "workflow-snapshot"
