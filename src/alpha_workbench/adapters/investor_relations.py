"""Official investor-relations feed and newsroom adapter.

Only configured official URLs are fetched. The adapter preserves source timing
and emits source evidence; it does not infer a graph relationship.
"""

from __future__ import annotations

import hashlib
import time
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from ..evidence import (
    DuckDBEvidenceLedger,
    EvidenceObservation,
    EvidenceRunReceipt,
    SourceDocument,
    TextEvidence,
)
from ..evidence.contracts import ExtractionProvenance
from .base import AdapterHealth
from .primary_documents import bounded_quote, visible_text
from .source_catalog import CatalogSource


class _NewsroomLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


class OfficialInvestorRelationsAdapter:
    """Collect official newsroom pages and RSS/Atom release summaries."""

    name = "official_investor_relations"
    requires_api_key = False

    def __init__(
        self,
        cache_dir: Path,
        *,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 0.2,
    ) -> None:
        self._cache_dir = cache_dir
        self._client = client or httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "User-Agent": "AgenticAlphaWorkbench/0.1 (public research collection)",
            },
        )
        self._min_interval_seconds = min_interval_seconds
        self._last_request_at = 0.0

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        """Collect configured sources passed as ``CatalogSource`` values.

        Query keys: ``sources`` (required), ``run_id`` (optional),
        ``max_items_per_feed`` (optional), and ``max_linked_pages`` (optional).
        No arbitrary URL is accepted here.
        """

        source_values = query.get("sources")
        if not isinstance(source_values, list):
            raise ValueError("sources must be a list of configured CatalogSource values")
        sources = [
            value if isinstance(value, CatalogSource) else CatalogSource.model_validate(value)
            for value in source_values
        ]
        for source in sources:
            if source.source_kind != "investor_relations":
                raise ValueError(
                    "OfficialInvestorRelationsAdapter accepts investor_relations sources only"
                )
        run_id = str(query.get("run_id", "official-ir-collection"))
        max_items = int(str(query.get("max_items_per_feed", 5)))
        if max_items < 1:
            raise ValueError("max_items_per_feed must be at least 1")
        max_linked_pages = int(str(query.get("max_linked_pages", 0)))
        if max_linked_pages < 0 or max_linked_pages > 5:
            raise ValueError("max_linked_pages must be between 0 and 5")

        observations: list[EvidenceObservation] = []
        for source in sources:
            raw, retrieved_at = self._fetch(source.url)
            self._write_cache(raw)
            if source.format in {"rss", "atom"}:
                observations.extend(
                    self._feed_observations(source, raw, retrieved_at, run_id, max_items)
                )
            else:
                observation = self._page_observation(source, raw, retrieved_at, run_id)
                if observation is not None:
                    observations.append(observation)
                observations.extend(
                    self._linked_page_observations(
                        source, raw, run_id=run_id, max_linked_pages=max_linked_pages
                    )
                )
        return observations

    def collect_and_record(
        self, query: dict[str, object], ledger: DuckDBEvidenceLedger
    ) -> EvidenceRunReceipt:
        """Collect and append an idempotent run receipt to the common ledger."""

        started_at = datetime.now(UTC)
        observations = self.collect(query)
        ledger.append_many(observations)
        finished_at = datetime.now(UTC)
        run_id = str(query.get("run_id", "official-ir-collection"))
        receipt = EvidenceRunReceipt(
            idempotency_key=self._receipt_key(run_id, observations),
            run_id=run_id,
            adapter_name=self.name,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            observation_idempotency_keys=tuple(item.idempotency_key for item in observations),
        )
        ledger.append_run_receipt(receipt)
        return receipt

    def _fetch(self, url: str) -> tuple[bytes, datetime]:
        remaining = self._min_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        response = self._client.get(url)
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response.content, datetime.now(UTC)

    def _write_cache(self, raw: bytes) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(raw).hexdigest()
        (self._cache_dir / f"{digest}.bin").write_bytes(raw)

    def _page_observation(
        self, source: CatalogSource, raw: bytes, retrieved_at: datetime, run_id: str
    ) -> EvidenceObservation | None:
        text = visible_text(raw)
        if not text:
            return None
        content_hash = hashlib.sha256(raw).hexdigest()
        # A landing page has no reliable historical publication timestamp. It is
        # explicitly timestamped at retrieval and is unsuitable for past as-of claims.
        document = SourceDocument(
            source_kind="investor_relations",
            source_tier="official",
            source_adapter=self.name,
            source_url=source.url,
            content_sha256=content_hash,
            issuer_entity_id=source.issuer_entity_id,
            observed_at=retrieved_at,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            usage_note=f"{source.usage_note}; page timestamp unavailable, using retrieval time",
            title=f"Official investor-relations page for {source.issuer_entity_id}",
        )
        excerpt = self._relevant_excerpt(text)
        return self._text_observation(
            document=document,
            text=excerpt,
            run_id=run_id,
            identifier=content_hash,
            section="official_newsroom_page",
        )

    def _linked_page_observations(
        self,
        source: CatalogSource,
        landing_page: bytes,
        *,
        run_id: str,
        max_linked_pages: int,
    ) -> list[EvidenceObservation]:
        """Follow a small allow-listed set of same-site newsroom release links."""

        if max_linked_pages == 0:
            return []
        parser = _NewsroomLinkParser()
        parser.feed(landing_page.decode("utf-8", errors="replace"))
        source_parsed = urlparse(source.url)
        source_host = source_parsed.netloc.lower()
        source_without_fragment = urlunparse(source_parsed._replace(fragment=""))
        links: list[str] = []
        for href in parser.hrefs:
            parsed = urlparse(urljoin(source.url, href))
            candidate = urlunparse(parsed._replace(fragment=""))
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != source_host:
                continue
            path = parsed.path.lower()
            if not any(token in path for token in ("news", "press", "release", "article", "story")):
                continue
            if candidate != source_without_fragment and candidate not in links:
                links.append(candidate)
        observations: list[EvidenceObservation] = []
        for link in links[:max_linked_pages]:
            raw, retrieved_at = self._fetch(link)
            self._write_cache(raw)
            text = visible_text(raw)
            if not text:
                continue
            content_hash = hashlib.sha256(raw).hexdigest()
            document = SourceDocument(
                source_kind="investor_relations",
                source_tier="official",
                source_adapter=self.name,
                source_url=link,
                content_sha256=content_hash,
                issuer_entity_id=source.issuer_entity_id,
                observed_at=retrieved_at,
                available_at=retrieved_at,
                retrieved_at=retrieved_at,
                usage_note=(
                    f"{source.usage_note}; official linked newsroom page; "
                    "publication timestamp unavailable, using retrieval time"
                ),
                title=f"Official linked newsroom page for {source.issuer_entity_id}",
            )
            observations.append(
                self._text_observation(
                    document=document,
                    text=self._relevant_excerpt(text),
                    run_id=run_id,
                    identifier=content_hash,
                    section="official_linked_newsroom_page",
                )
            )
        return observations

    @staticmethod
    def _relevant_excerpt(text: str) -> str:
        """Prefer an explicit relationship window while retaining a bounded fallback."""

        lowered = text.lower()
        keywords = (
            "rely on",
            "relies on",
            "supply chain",
            "supplier",
            "manufactur",
            "capacity",
            "foundry",
            "customer",
        )
        matches = [lowered.find(keyword) for keyword in keywords if lowered.find(keyword) >= 0]
        if not matches:
            return text[:1200]
        start = max(0, min(matches) - 400)
        return text[start : start + 1200]

    def _feed_observations(
        self,
        source: CatalogSource,
        raw: bytes,
        retrieved_at: datetime,
        run_id: str,
        max_items: int,
    ) -> list[EvidenceObservation]:
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise ValueError(f"invalid {source.format} feed from {source.url}") from exc
        items = list(root.findall(".//item"))
        if not items:
            namespace = "{http://www.w3.org/2005/Atom}"
            items = list(root.findall(f".//{namespace}entry"))
        observations: list[EvidenceObservation] = []
        for index, item in enumerate(items[:max_items]):
            title = self._child_text(item, "title") or "Official investor-relations release"
            description = self._child_text(item, "description") or self._child_text(item, "summary")
            text = visible_text(description or title)
            if not text:
                continue
            link = self._child_text(item, "link") or self._atom_link(item) or source.url
            published_at = self._published_at(item, retrieved_at)
            external_id = self._child_text(item, "guid") or link
            item_hash = hashlib.sha256(
                f"{title}\n{text}\n{link}\n{published_at.isoformat()}".encode()
            ).hexdigest()
            document = SourceDocument(
                source_kind="investor_relations",
                source_tier="official",
                source_adapter=self.name,
                source_url=link,
                content_sha256=item_hash,
                issuer_entity_id=source.issuer_entity_id,
                observed_at=published_at,
                available_at=published_at,
                retrieved_at=retrieved_at,
                usage_note=f"{source.usage_note}; official feed summary",
                external_id=external_id,
                title=title,
            )
            observation = self._text_observation(
                document=document,
                text=text[:1200],
                run_id=run_id,
                identifier=f"{external_id}:{index}",
                section="official_feed_item",
            )
            observations.append(observation)
        return observations

    @staticmethod
    def _child_text(item: ElementTree.Element, local_name: str) -> str | None:
        for child in item:
            if child.tag.split("}")[-1] == local_name and child.text:
                return child.text.strip()
        return None

    @staticmethod
    def _atom_link(item: ElementTree.Element) -> str | None:
        for child in item:
            if child.tag.split("}")[-1] == "link" and child.attrib.get("href"):
                return str(child.attrib["href"])
        return None

    def _published_at(self, item: ElementTree.Element, fallback: datetime) -> datetime:
        value = self._child_text(item, "pubDate") or self._child_text(item, "published")
        if not value:
            return fallback
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return fallback
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def _text_observation(
        self,
        *,
        document: SourceDocument,
        text: str,
        run_id: str,
        identifier: str,
        section: str,
    ) -> EvidenceObservation:
        quote = bounded_quote(text)
        key_material = f"{document.content_sha256}:{identifier}:{section}:{quote}"
        return EvidenceObservation(
            idempotency_key=f"ir:{hashlib.sha256(key_material.encode('utf-8')).hexdigest()}",
            document=document,
            mentioned_entity_ids=(document.issuer_entity_id,),
            payload=TextEvidence(
                text=text,
                exact_quote=quote,
                character_start=0,
                character_end=len(quote),
                section=section,
            ),
            extraction=ExtractionProvenance(
                extractor_name=self.name, extractor_version="1", run_id=run_id
            ),
        )

    @staticmethod
    def _receipt_key(run_id: str, observations: list[EvidenceObservation]) -> str:
        material = ":".join([run_id, *(item.idempotency_key for item in observations)])
        return f"ir-receipt:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"
