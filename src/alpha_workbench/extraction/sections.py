"""Offline, deterministic selection of filing passages relevant to graph evidence."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel, Field

from ..adapters.base import SourceSnapshot

_KEYWORDS = (
    "competitor",
    "competition",
    "compete",
    "substitute",
    "supplier",
    "supply chain",
    "supply agreement",
    "wafer supply",
    "manufactur",
    "foundry",
    "lithography",
    "deposition",
    "etch",
    "capacity",
    "customer",
    "customer concentration",
    "design win",
    "joint development",
    "collaboration",
    "co-investment",
    "license",
    "sole source",
    "single source",
    "packaging",
)

# These phrases signal an actual commercial relationship more strongly than a
# generic industry reference (for example, "manufacturing" in a product-market
# description). They rank passages; they do not create an edge by themselves.
_RELATIONSHIP_PHRASES = (
    "we compete with",
    "our competitors include",
    "competes with",
    "alternative to",
    "we utilize",
    "we purchase",
    "we engage",
    "we rely on",
    "contract manufacturer",
    "third-party manufacturer",
    "supply agreement",
    "manufacturing capacity",
    "supply constraints",
    "wafer supply agreement",
    "design win",
    "joint development",
    "strategic collaboration",
    "customer agreement",
    "license agreement",
    "sole source",
    "single source",
)

# SEC Inline XBRL documents commonly begin with a hidden ``ix:header`` containing
# taxonomy labels such as ``ManufacturingProduction...``.  Those labels are not
# filing narrative and must never be offered to the evidence model.
_NON_NARRATIVE_TAGS = {
    "script",
    "style",
    "ix:header",
    "ix:hidden",
    "ix:references",
    "ix:resources",
    "xbrli:context",
    "xbrli:unit",
    "link:schemaref",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_tag_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_tag_depth or tag.lower() in _NON_NARRATIVE_TAGS:
            self._ignored_tag_depth += 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._ignored_tag_depth:
            self._ignored_tag_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_tag_depth:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


class DocumentPassage(BaseModel):
    snapshot_sha256: str = Field(min_length=64, max_length=64)
    source_url: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    text: str = Field(min_length=1)
    matching_keywords: list[str] = Field(min_length=1)


class FilingSectionSelector:
    """Select bounded evidence passages; it makes no claim about relationships."""

    def __init__(self, *, window_characters: int = 900) -> None:
        if window_characters < 100:
            raise ValueError("window_characters must be at least 100")
        self._window_characters = window_characters

    def select(
        self, cached_html: Path, snapshot: SourceSnapshot, *, max_passages: int = 20
    ) -> list[DocumentPassage]:
        parser = _TextExtractor()
        parser.feed(cached_html.read_text(encoding="utf-8", errors="replace"))
        document = parser.text()
        lower_document = document.lower()
        candidates: list[tuple[int, int, int, DocumentPassage]] = []
        for keyword in _KEYWORDS:
            for match in re.finditer(re.escape(keyword), lower_document):
                start_match = match.start()
                start = max(0, start_match - self._window_characters // 2)
                end = min(len(document), start_match + self._window_characters // 2)
                text = document[start:end]
                text_lower = text.lower()
                matched = [term for term in _KEYWORDS if term in text_lower]
                relationship_score = sum(
                    phrase in text_lower for phrase in _RELATIONSHIP_PHRASES
                )
                candidates.append(
                    (
                        relationship_score,
                        len(matched),
                        start,
                        DocumentPassage(
                            snapshot_sha256=snapshot.content_sha256,
                            source_url=snapshot.source_url,
                            start_offset=start,
                            end_offset=end,
                            text=text,
                            matching_keywords=matched,
                        ),
                    )
                )

        passages: list[DocumentPassage] = []
        for _, _, _, candidate in sorted(candidates, key=lambda item: item[:3], reverse=True):
            # Consecutive keyword matches normally point into the same paragraph.
            # Retain the strongest representative, not near-duplicate model calls.
            if any(
                abs(candidate.start_offset - existing.start_offset)
                < self._window_characters // 2
                for existing in passages
            ):
                continue
            passages.append(candidate)
            if len(passages) >= max_passages:
                break
        return passages
