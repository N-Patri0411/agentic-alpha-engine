from datetime import UTC, datetime
from pathlib import Path

from alpha_workbench.adapters.base import SourceSnapshot
from alpha_workbench.extraction import FilingSectionSelector


def test_selector_returns_sourced_bounded_passages(tmp_path: Path) -> None:
    cached = tmp_path / "fixture.html"
    cached.write_text(
        "<html><body><p>Our manufacturing capacity depends on a limited supplier base. "
        "A supply chain disruption could delay advanced packaging.</p></body></html>",
        encoding="utf-8",
    )
    snapshot = SourceSnapshot(
        source="sec_filings",
        source_url="https://example.test/filing",
        retrieved_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        available_at=datetime.now(UTC),
        content_sha256="a" * 64,
        usage_note="fixture",
    )
    passages = FilingSectionSelector(window_characters=100).select(cached, snapshot)
    assert passages
    assert all(passage.snapshot_sha256 == snapshot.content_sha256 for passage in passages)
    assert "manufactur" in passages[0].matching_keywords


def test_selector_returns_no_passage_when_terms_are_absent(tmp_path: Path) -> None:
    cached = tmp_path / "empty.html"
    cached.write_text("<p>General corporate information.</p>", encoding="utf-8")
    snapshot = SourceSnapshot(
        source="sec_filings",
        source_url="https://example.test/filing",
        retrieved_at=datetime.now(UTC),
        observed_at=datetime.now(UTC),
        available_at=datetime.now(UTC),
        content_sha256="b" * 64,
        usage_note="fixture",
    )
    assert FilingSectionSelector().select(cached, snapshot) == []
