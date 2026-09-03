from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from alpha_workbench.evidence import (
    DuckDBEvidenceLedger,
    EvidenceObservation,
    EvidenceRunReceipt,
    SourceCatalogEntry,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.evidence.contracts import ExtractionProvenance


def _document(*, available_at: datetime | None = None) -> SourceDocument:
    observed_at = datetime(2026, 1, 5, tzinfo=UTC)
    available = available_at or observed_at + timedelta(hours=2)
    return SourceDocument(
        source_kind="sec_filing",
        source_tier="primary",
        source_adapter="sec_filings",
        source_url="https://example.test/filing",
        content_sha256="a" * 64,
        issuer_entity_id="NVDA",
        observed_at=observed_at,
        available_at=available,
        retrieved_at=available + timedelta(minutes=1),
        usage_note="public fixture",
    )


def _observation(
    *, key: str = "obs-1", available_at: datetime | None = None
) -> EvidenceObservation:
    return EvidenceObservation(
        idempotency_key=key,
        document=_document(available_at=available_at),
        mentioned_entity_ids=("NVDA", "TSM"),
        payload=TextEvidence(
            text="We rely on TSMC for manufacturing.",
            exact_quote="rely on TSMC",
            character_start=0,
            character_end=35,
            section="Business",
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="run-1"
        ),
    )


def test_evidence_records_are_immutable_and_validate_provenance() -> None:
    observation = _observation()
    with pytest.raises(ValidationError):
        observation.idempotency_key = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="available_at cannot precede"):
        _document(available_at=datetime(2026, 1, 4, tzinfo=UTC))
    with pytest.raises(ValidationError, match="issuer_entity_id"):
        EvidenceObservation(
            idempotency_key="missing-issuer",
            document=_document(),
            mentioned_entity_ids=("TSM",),
            payload=TextEvidence(
                text="TSMC supplies chips.",
                exact_quote="supplies chips",
                character_start=0,
                character_end=20,
            ),
            extraction=ExtractionProvenance(
                extractor_name="fixture", extractor_version="1", run_id="run-1"
            ),
        )


def test_evidence_ledger_is_append_only_idempotent_and_as_of_safe(tmp_path: Path) -> None:
    early = _observation(key="early")
    late = _observation(key="late", available_at=datetime(2026, 1, 8, tzinfo=UTC))
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")

    assert ledger.append(early) is True
    assert ledger.append(early) is False
    assert ledger.append_many([early, late]) == 1
    assert ledger.count_observations() == 2
    as_of = ledger.observations_as_of(datetime(2026, 1, 6, tzinfo=UTC))
    assert [item.idempotency_key for item in as_of] == ["early"]
    ledger.close()


def test_evidence_ledger_selects_observations_by_collection_run(tmp_path: Path) -> None:
    first = _observation(key="first")
    second = _observation(key="second").model_copy(
        update={
            "extraction": ExtractionProvenance(
                extractor_name="web_discovery", extractor_version="1", run_id="run-2"
            )
        }
    )
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")
    ledger.append_many([first, second])

    assert [item.idempotency_key for item in ledger.observations_for_run("run-1")] == ["first"]
    assert ledger.observations_for_run("run-1", source_adapter="web_discovery") == []
    assert [item.idempotency_key for item in ledger.observations_for_run("run-2")] == ["second"]
    ledger.close()


def test_catalog_and_run_receipts_are_written_once(tmp_path: Path) -> None:
    now = datetime(2026, 1, 5, tzinfo=UTC)
    ledger = DuckDBEvidenceLedger(tmp_path / "evidence.duckdb")
    source = SourceCatalogEntry(
        idempotency_key="source-nvda-ir",
        issuer_entity_id="NVDA",
        source_kind="investor_relations",
        source_tier="official",
        source_adapter="investor_relations",
        source_url="https://investor.nvidia.com/news/default.aspx",
        usage_note="official investor relations fixture",
        registered_at=now,
    )
    receipt = EvidenceRunReceipt(
        idempotency_key="receipt-run-1",
        run_id="run-1",
        adapter_name="sec_filings",
        status="completed",
        started_at=now,
        finished_at=now + timedelta(minutes=1),
        observation_idempotency_keys=("obs-1",),
    )

    assert ledger.register_source(source) is True
    assert ledger.register_source(source) is False
    assert ledger.append_run_receipt(receipt) is True
    assert ledger.append_run_receipt(receipt) is False
    ledger.close()
