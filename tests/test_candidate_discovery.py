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


def test_candidate_discovery_selects_all_text_but_not_market_bars() -> None:
    official = _text_observation()
    discovery = official.model_copy(
        update={
            "idempotency_key": "discovery-fixture",
            "document": _document(tier="discovery"),
        }
    )
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
        observations=[market, discovery, official], maximum_observations=3
    )

    assert selected == [discovery, official]
    assert receipt.skipped_non_text_count == 1
    assert receipt.skipped_non_text_or_non_primary_count == 1
    assert receipt.selected_source_tiers == {"discovery": 1, "official": 1}


def test_candidate_discovery_converts_original_source_span_to_passage() -> None:
    passage = observation_to_passage(_text_observation())

    assert passage.start_offset == 0
    assert passage.end_offset == 58
    assert passage.matching_keywords == ["candidate_discovery"]
    assert passage.source_tier == "official"
    assert passage.source_kind == "investor_relations"
    assert passage.evidence_basis == "full_text"


def test_candidate_discovery_marks_discovery_summary_as_weak_provenance() -> None:
    observation = _text_observation().model_copy(
        update={"document": _document(tier="discovery")}
    )
    passage = observation_to_passage(observation)
    assert passage.evidence_basis == "discovery_summary"


def test_candidate_discovery_maximizes_new_entity_pair_coverage() -> None:
    repeated = _text_observation().model_copy(
        update={
            "idempotency_key": "repeat",
            "mentioned_entity_ids": ("NVDA", "AMD"),
        }
    )
    novel = _text_observation().model_copy(
        update={
            "idempotency_key": "novel",
            "mentioned_entity_ids": ("NVDA", "TSM"),
        }
    )
    selected, _ = select_candidate_discovery_observations(
        observations=[repeated, novel, repeated.model_copy(update={"idempotency_key": "repeat-2"})],
        maximum_observations=2,
    )
    assert {item.idempotency_key for item in selected} == {"repeat", "novel"}


def test_candidate_discovery_uses_earliest_observation_on_coverage_tie() -> None:
    early = _text_observation().model_copy(update={"idempotency_key": "early"})
    late = _text_observation().model_copy(
        update={
            "idempotency_key": "late",
            "document": _document().model_copy(
                update={"available_at": datetime(2026, 9, 5, tzinfo=UTC)}
            ),
        }
    )
    selected, _ = select_candidate_discovery_observations(
        observations=[late, early], maximum_observations=1
    )
    assert selected[0].idempotency_key == "early"


def test_candidate_discovery_rejects_empty_eligible_input() -> None:
    with pytest.raises(ValueError, match="no text observations"):
        select_candidate_discovery_observations(observations=[], maximum_observations=1)
