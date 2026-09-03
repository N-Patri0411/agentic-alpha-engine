"""Small, deterministic helpers shared by official primary-source adapters."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_NON_NARRATIVE_TAGS = {
    "aside",
    "footer",
    "form",
    "header",
    "nav",
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


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_depth or tag.lower() in _NON_NARRATIVE_TAGS:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def visible_text(raw_document: bytes | str) -> str:
    """Return visible HTML narrative, excluding script and Inline-XBRL metadata."""

    text = (
        raw_document.decode("utf-8", errors="replace")
        if isinstance(raw_document, bytes)
        else raw_document
    )
    parser = _VisibleTextParser()
    parser.feed(text)
    return parser.text()


def bounded_quote(text: str, *, maximum_characters: int = 280) -> str:
    """Return a reproducible non-empty quote from an already bounded passage."""

    normalized = text.strip()
    if not normalized:
        raise ValueError("text must not be empty")
    if len(normalized) <= maximum_characters:
        return normalized
    sentence_end = normalized.find(". ", 1, maximum_characters)
    if sentence_end != -1:
        return normalized[: sentence_end + 1]
    return normalized[:maximum_characters]
