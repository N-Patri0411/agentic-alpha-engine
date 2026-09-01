"""Offline, deterministic selection of filing passages relevant to graph evidence."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from pydantic import BaseModel, Field

from ..adapters.base import SourceSnapshot

_KEYWORDS = (
    "supplier",
    "supply chain",
    "manufactur",
    "foundry",
    "capacity",
    "customer concentration",
    "sole source",
    "single source",
    "packaging",
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

    def __init__(self, *, window_characters: int = 500) -> None:
        if window_characters < 100:
            raise ValueError("window_characters must be at least 100")
        self._window_characters = window_characters

    def select(
        self, cached_html: Path, snapshot: SourceSnapshot, *, max_passages: int = 20
    ) -> list[DocumentPassage]:
        parser = _TextExtractor()
        parser.feed(cached_html.read_text(encoding="utf-8", errors="replace"))
        document = parser.text()
        passages: list[DocumentPassage] = []
        lower_document = document.lower()
        cursor = 0
        while cursor < len(document) and len(passages) < max_passages:
            matches = [keyword for keyword in _KEYWORDS if keyword in lower_document[cursor:]]
            if not matches:
                break
            positions = [lower_document.find(keyword, cursor) for keyword in matches]
            start_match = min(position for position in positions if position >= 0)
            start = max(0, start_match - self._window_characters // 2)
            end = min(len(document), start_match + self._window_characters)
            text = document[start:end]
            matched = [keyword for keyword in _KEYWORDS if keyword in text.lower()]
            passages.append(
                DocumentPassage(
                    snapshot_sha256=snapshot.content_sha256,
                    source_url=snapshot.source_url,
                    start_offset=start,
                    end_offset=end,
                    text=text,
                    matching_keywords=matched,
                )
            )
            cursor = end
        return passages
