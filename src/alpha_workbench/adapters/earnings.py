"""Official earnings evidence collection with transparent fallback source labels.

This adapter captures text that a company has made available itself, an SEC
8-K exhibit, or an official investor-relations release. It deliberately does
not transcribe audio or infer a relationship; downstream extraction and graph
agents interpret these immutable observations.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal

import httpx
from pydantic import BaseModel, Field, HttpUrl, field_validator

from ..evidence import EvidenceObservation, SourceDocument, TextEvidence
from ..evidence.contracts import ExtractionProvenance
from .base import AdapterHealth
from .rate_limit import RequestPacer
from .sec import SecFilingAdapter

EarningsDocumentKind = Literal[
    "official_transcript",
    "official_webcast",
    "official_press_release",
    "sec_8k_exhibit",
    "sec_6k_exhibit",
]


class EarningsDocumentRequest(BaseModel):
    """One known official earnings-related document to retrieve."""

    issuer_entity_id: str = Field(min_length=1)
    source_url: HttpUrl
    published_at: datetime
    kind: EarningsDocumentKind
    title: str | None = None
    mentioned_entity_ids: tuple[str, ...] = ()

    @field_validator("published_at")
    @classmethod
    def _published_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("published_at must include a timezone")
        return value


class SecEarningsDocumentDiscoverer:
    """Find bounded SEC 8-K EX-99 earnings documents for the fallback adapter."""

    def __init__(self, sec_filings: SecFilingAdapter) -> None:
        self._sec_filings = sec_filings

    def discover(
        self, *, cik: str, issuer_entity_id: str, max_documents: int = 2
    ) -> list[EarningsDocumentRequest]:
        if max_documents < 1:
            raise ValueError("max_documents must be at least 1")
        filings = self._sec_filings.discover(
            {"cik": cik, "forms": ["8-K", "6-K"], "include_exhibits": True}
        )
        results: list[EarningsDocumentRequest] = []
        for filing in filings:
            if filing.get("document_kind") != "exhibit_99":
                continue
            filing_date = datetime.fromisoformat(str(filing["filing_date"])).replace(tzinfo=UTC)
            form = str(filing["form"])
            kind: EarningsDocumentKind = "sec_6k_exhibit" if form == "6-K" else "sec_8k_exhibit"
            results.append(
                EarningsDocumentRequest.model_validate(
                    {
                        "issuer_entity_id": issuer_entity_id,
                        "source_url": str(filing["source_url"]),
                        "published_at": filing_date,
                        "kind": kind,
                        "title": f"SEC earnings exhibit {filing['accession_number']}",
                    }
                )
            )
            if len(results) == max_documents:
                break
        return results


class _VisibleTextParser(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_depth or tag.lower() in self._IGNORED_TAGS:
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


def _readable_text(content: bytes) -> str:
    """Return visible text from HTML, or the decoded text for plain transcripts."""

    decoded = content.decode("utf-8", errors="replace")
    if "<" not in decoded or ">" not in decoded:
        return re.sub(r"\s+", " ", decoded).strip()
    parser = _VisibleTextParser()
    parser.feed(decoded)
    return parser.text()


def _text_windows(text: str, *, max_windows: int, maximum_characters: int) -> list[tuple[int, str]]:
    if not text:
        return []
    windows: list[tuple[int, str]] = []
    start = 0
    while start < len(text) and len(windows) < max_windows:
        end = min(len(text), start + maximum_characters)
        if end < len(text):
            sentence_break = text.rfind(". ", start, end)
            if sentence_break > start + maximum_characters // 2:
                end = sentence_break + 1
        window = text[start:end].strip()
        if window:
            windows.append((start, window))
        start = max(end, start + 1)
    return windows


def _source_metadata(
    kind: EarningsDocumentKind,
) -> tuple[
    Literal["sec_filing", "investor_relations", "earnings_call"],
    Literal["primary", "official"],
    str,
]:
    if kind in {"sec_8k_exhibit", "sec_6k_exhibit"}:
        return ("sec_filing", "primary", "SEC earnings exhibit; public filing")
    if kind == "official_press_release":
        return ("investor_relations", "official", "Official investor-relations earnings release")
    if kind == "official_webcast":
        return ("earnings_call", "official", "Official earnings webcast page or transcript")
    return ("earnings_call", "official", "Official earnings-call transcript")


class OfficialEarningsEvidenceAdapter:
    """Fetch configured official earnings documents and emit text observations."""

    name = "official_earnings_evidence"
    requires_api_key = False

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 0.2,
        now: Callable[[], datetime] | None = None,
        pacer: RequestPacer | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=20.0, follow_redirects=True)
        self._now = now or (lambda: datetime.now(UTC))
        self._pacer = pacer or RequestPacer(min_interval_seconds)

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        raw_documents = query.get("documents")
        if not isinstance(raw_documents, list):
            raise ValueError("documents must be a list of official earnings document definitions")
        raw_max_windows = query.get("max_windows_per_document", 3)
        if not isinstance(raw_max_windows, int):
            raise ValueError("max_windows_per_document must be an integer")
        max_windows = raw_max_windows
        if max_windows < 1:
            raise ValueError("max_windows_per_document must be at least 1")
        run_id = str(query.get("run_id", "earnings-collection"))
        observations: list[EvidenceObservation] = []
        for raw_document in raw_documents:
            request = EarningsDocumentRequest.model_validate(raw_document)
            observations.extend(
                self._collect_document(request, run_id=run_id, max_windows=max_windows)
            )
        return observations

    def _collect_document(
        self, request: EarningsDocumentRequest, *, run_id: str, max_windows: int
    ) -> list[EvidenceObservation]:
        self._pacer.wait()
        response = self._client.get(str(request.source_url))
        response.raise_for_status()
        content = response.content
        content_sha256 = hashlib.sha256(content).hexdigest()
        text = _readable_text(content)
        if not text:
            raise ValueError(
                f"official earnings document had no readable text: {request.source_url}"
            )
        source_kind, source_tier, usage_note = _source_metadata(request.kind)
        retrieved_at = self._now()
        mentioned = (request.issuer_entity_id,) + tuple(
            entity
            for entity in request.mentioned_entity_ids
            if entity != request.issuer_entity_id
        )
        document = SourceDocument(
            source_kind=source_kind,
            source_tier=source_tier,
            source_adapter=self.name,
            source_url=str(request.source_url),
            content_sha256=content_sha256,
            issuer_entity_id=request.issuer_entity_id,
            observed_at=request.published_at,
            available_at=request.published_at,
            retrieved_at=retrieved_at,
            usage_note=usage_note,
            title=request.title,
        )
        result: list[EvidenceObservation] = []
        for index, (start, window) in enumerate(
            _text_windows(text, max_windows=max_windows, maximum_characters=1_500)
        ):
            quote_end = min(len(window), 300)
            quote = window[:quote_end]
            result.append(
                EvidenceObservation(
                    idempotency_key=(
                        f"{self.name}:{content_sha256}:{request.issuer_entity_id}:{index}"
                    ),
                    document=document,
                    mentioned_entity_ids=mentioned,
                    payload=TextEvidence(
                        text=window,
                        exact_quote=quote,
                        character_start=start,
                        character_end=start + len(window),
                        section=request.kind,
                    ),
                    extraction=ExtractionProvenance(
                        extractor_name=self.name,
                        extractor_version="1",
                        run_id=run_id,
                    ),
                )
            )
        return result
