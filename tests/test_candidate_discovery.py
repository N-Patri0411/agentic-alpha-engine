from datetime import UTC, datetime

import pytest

from alpha_workbench.candidate_discovery import (
    observation_to_passage,
    select_candidate_discovery_observations,
)
from alpha_workbench.evidence import (
    EvidenceObservation,
    ExtractionProvenance,
    MarketBar,
    SourceDocument,
    TextEvidence,
)

NOW = datetime(2026, 9, 4, tzinfo=UTC)


def _document(*, tier: str = "official") -> SourceDocument:
    return SourceDocument(
        source_kind="investor_relations",
        source_tier=tier,  # type: ignore[arg-type]
        source_adapter="fixture",
        source_url="https://example.test/source",
        content_sha256="b" * 64,
        issuer_entity_id="NVDA",
        observed_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        usage_note="fixture",
    )


def _text_observation() -> EvidenceObservation:
    return EvidenceObservation(
        idempotency_key="text-fixture",
        document=_document(),
        mentioned_entity_ids=("NVDA",),
        payload=TextEvidence(
            text="NVIDIA announced a joint development program with Microsoft.",
            exact_quote="joint development program",
            character_start=0,
            character_end=58,
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture",
            extractor_version="1",
            run_id="candidate-fixture",
        ),
    )


def test_candidate_discovery_selects_only_primary_or_official_text() -> None:
    official = _text_observation()
    market = official.model_copy(
        update={
            "idempotency_key": "market-fixture",
            "payload": MarketBar(
                symbol="NVDA",
                bar_start=NOW,
                bar_end=datetime(2026, 9, 4, 21, tzinfo=UTC),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1,
            ),
        }
    )

    selected, receipt = select_candidate_discovery_observations(
        observations=[market, official], maximum_observations=2
    )

    assert selected == [official]
    assert receipt.skipped_non_text_or_non_primary_count == 1


def test_candidate_discovery_converts_original_source_span_to_passage() -> None:
    passage = observation_to_passage(_text_observation())

    assert passage.start_offset == 0
    assert passage.end_offset == 58
    assert passage.matching_keywords == ["candidate_discovery"]


def test_candidate_discovery_rejects_empty_eligible_input() -> None:
    with pytest.raises(ValueError, match="no primary or official text"):
        select_candidate_discovery_observations(observations=[], maximum_observations=1)
