from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.agents.graph_adjudicator import GraphAdjudicatorAgent
from alpha_workbench.evidence import (
    DuckDBEvidenceLedger,
    EvidenceIntakeService,
    EvidenceObservation,
    EvidenceRunReceipt,
    ExtractionProvenance,
    NightlyGraphConsolidator,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.graph_registry import EntityRegistry, GraphPublisher, GraphSnapshot
from alpha_workbench.llm.models import FakeLLMClient

REGISTRY = Path("data/entities/semiconductor_v1.json")
SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
AT = datetime(2026, 5, 1, tzinfo=UTC)


def _observation() -> EvidenceObservation:
    text = "NVIDIA relies on TSMC to manufacture advanced products."
    return EvidenceObservation(
        idempotency_key="runtime-observation",
        document=SourceDocument(
            source_kind="sec_filing",
            source_tier="primary",
            source_adapter="fixture",
            source_url="https://example.test/runtime",
            content_sha256="c" * 64,
            issuer_entity_id="NVDA",
            observed_at=AT,
            available_at=AT,
            retrieved_at=AT,
            usage_note="runtime fixture",
        ),
        mentioned_entity_ids=("NVDA",),
        payload=TextEvidence(
            text=text,
            exact_quote=text,
            character_start=0,
            character_end=len(text),
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="runtime"
        ),
    )


class _WorkingAdapter:
    name = "fixture_source"

    def __init__(self, observation: EvidenceObservation | None = None) -> None:
        self.observation = observation or _observation()

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        del query
        return [self.observation]


class _FailingAdapter:
    name = "broken_source"

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        del query
        raise RuntimeError("fixture source unavailable")


def test_event_intake_records_completed_and_failed_source_receipts(tmp_path: Path) -> None:
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")
    intake = EvidenceIntakeService(
        ledger, {"fixture_source": _WorkingAdapter(), "broken_source": _FailingAdapter()}
    )

    completed = intake.collect(adapter_name="fixture_source", query={}, run_id="event-1")
    failed = intake.collect(adapter_name="broken_source", query={}, run_id="event-2")

    assert completed.status == "completed"
    assert failed.status == "failed"
    assert failed.errors == ("RuntimeError: fixture source unavailable",)
    assert ledger.count_observations() == 1
    ledger.close()


def test_nightly_consolidation_publishes_from_ledger_as_of_time(tmp_path: Path) -> None:
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")
    source = _WorkingAdapter()
    intake = EvidenceIntakeService(ledger, {"fixture_source": source})
    receipt: EvidenceRunReceipt = intake.collect(
        adapter_name="fixture_source", query={}, run_id="event-1"
    )
    registry = EntityRegistry.from_json(REGISTRY)
    adjudicator = GraphAdjudicatorAgent(
        FakeLLMClient(
            {
                "action": "update_state",
                "upstream_entity_id": "TSM",
                "downstream_entity_id": "NVDA",
                "relationship_type": "manufacturing_dependency",
                "supporting_observation_ids": [str(source.observation.observation_id)],
                "rationale": "The source confirms the manufacturing dependency.",
            }
        ),
        registry,
        GraphPublisher(registry),
    )

    report = NightlyGraphConsolidator(ledger, adjudicator).consolidate(
        current_snapshot=GraphSnapshot.from_json(SNAPSHOT),
        as_of_time=AT,
        next_snapshot_id="runtime-nightly",
        snapshot_path=tmp_path / "runtime-nightly.json",
    )

    assert receipt.status == "completed"
    assert report.published_snapshot_id == "runtime-nightly"
    assert (tmp_path / "runtime-nightly.json").exists()
    ledger.close()
