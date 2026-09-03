from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.graph_build import select_graph_build_observations
from alpha_workbench.graph_registry import GraphSnapshot

SNAPSHOT = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")
NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _observation(*, source_tier: str, entities: tuple[str, str], url: str) -> EvidenceObservation:
    text = f"{entities[0]} has a documented relationship with {entities[1]}."
    return EvidenceObservation(
        idempotency_key=f"fixture:{source_tier}:{url}",
        document=SourceDocument(
            source_kind="web_discovery",
            source_tier=source_tier,  # type: ignore[arg-type]
            source_adapter="fixture",
            source_url=url,
            content_sha256="a" * 64,
            issuer_entity_id=entities[0],
            observed_at=NOW,
            available_at=NOW,
            retrieved_at=NOW,
            usage_note="fixture evidence",
        ),
        mentioned_entity_ids=entities,
        payload=TextEvidence(
            text=text,
            exact_quote=text,
            character_start=0,
            character_end=len(text),
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="fixture-run"
        ),
    )


def test_graph_build_selection_prefers_unseen_official_pairs() -> None:
    selected, receipt = select_graph_build_observations(
        observations=[
            _observation(
                source_tier="official",
                entities=("TSM", "NVDA"),
                url="https://example.test/existing",
            ),
            _observation(
                source_tier="discovery",
                entities=("AMD", "GFS"),
                url="https://example.test/discovery",
            ),
            _observation(
                source_tier="official",
                entities=("ASML", "TSM"),
                url="https://example.test/asml",
            ),
            _observation(
                source_tier="official",
                entities=("NVDA", "Hynix"),
                url="https://example.test/hynix",
            ),
        ],
        current_snapshot=GraphSnapshot.from_json(SNAPSHOT),
        maximum_observations=2,
    )

    assert [item.mentioned_entity_ids for item in selected] == [
        ("ASML", "TSM"),
        ("NVDA", "Hynix"),
    ]
    assert receipt.skipped_existing_pair_count == 1
