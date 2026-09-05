"""Controlled retrieval of full text from reviewed discovery-result domains."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..evidence import EvidenceObservation, SourceDocument, TextEvidence
from ..evidence.contracts import ExtractionProvenance
from .base import AdapterHealth
from .primary_documents import bounded_quote, visible_text

_RELATIONSHIP_TERMS = (
    "competitor",
    "compete",
    "competition",
    "substitution",
    "supply chain",
    "supplier",
    "supply agreement",
    "manufactur",
    "foundry",
    "capacity",
    "partner",
    "collaboration",
    "customer",
    "design win",
    "joint development",
    "contract",
    "dependency",
    "designed for",
    "production",
)


class WebFetchPolicy(BaseModel):
    """Tracked domain allow-list for content retrieval after discovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    schema_version: str = "1"
    allowed_hosts: tuple[str, ...] = Field(min_length=1)
    official_hosts: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, path: Path) -> WebFetchPolicy:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def allows(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in set(self.allowed_hosts)

    def source_tier(self, url: str) -> str:
        """Return official only for hosts explicitly reviewed as company sources."""

        return "official" if urlparse(url).hostname in set(self.official_hosts) else "discovery"


class WebPageContentAdapter:
    """Fetch one allow-listed discovery result and retain ranked exact passages.

    This is intentionally not a general crawler: callers pass a prior discovery
    observation, only hosts in the tracked policy can be read, redirects must
    remain allow-listed, and the raw response has a strict size cap.
    """

    name = "web_page_content"
    requires_api_key = False

    def __init__(
        self,
        cache_dir: Path,
        policy: WebFetchPolicy,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
        maximum_bytes: int = 1_000_000,
        maximum_redirects: int = 3,
    ) -> None:
        if maximum_bytes < 1 or maximum_redirects < 0:
            raise ValueError("maximum_bytes must be positive and maximum_redirects non-negative")
        self._cache_dir = cache_dir
        self._policy = policy
        self._client = client or httpx.Client(
            timeout=15.0,
            follow_redirects=False,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "AgenticAlphaWorkbench/0.1 (public research collection)",
            },
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._maximum_bytes = maximum_bytes
        self._maximum_redirects = maximum_redirects

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        raw_candidate = query.get("candidate")
        if not isinstance(raw_candidate, dict):
            raise ValueError("candidate must be a prior discovery observation")
        candidate = EvidenceObservation.model_validate(raw_candidate)
        if candidate.document.source_kind != "web_discovery":
            raise ValueError("web content can be fetched only from a discovery observation")
        if not self._policy.allows(candidate.document.source_url):
            raise ValueError("candidate host is not in the reviewed web-fetch allow-list")
        raw_aliases = query.get("entity_aliases")
        if not isinstance(raw_aliases, dict):
            raise ValueError("entity_aliases must map approved entity IDs to aliases")
        aliases = self._aliases(raw_aliases)
        max_passages = int(str(query.get("max_passages", 2)))
        if max_passages < 1 or max_passages > 3:
            raise ValueError("max_passages must be between 1 and 3")
        raw, resolved_url = self._fetch(candidate.document.source_url)
        content_hash = hashlib.sha256(raw).hexdigest()
        self._cache_raw(content_hash, raw)
        text = visible_text(raw)
        if not text:
            raise ValueError("fetched page did not contain readable HTML/text")
        passages = self._rank_passages(text, aliases, max_passages=max_passages)
        if not passages:
            return []
        retrieved_at = self._now()
        document = SourceDocument(
            source_kind="web_discovery",
            source_tier=self._policy.source_tier(resolved_url),  # type: ignore[arg-type]
            source_adapter=self.name,
            source_url=resolved_url,
            content_sha256=content_hash,
            issuer_entity_id=candidate.document.issuer_entity_id,
            observed_at=candidate.document.observed_at,
            available_at=candidate.document.available_at,
            retrieved_at=retrieved_at,
            usage_note=(
                "Full text retrieved from a reviewed discovery-result host; "
                "tier is determined by the tracked host policy"
            ),
            external_id=f"discovery:{candidate.observation_id}",
            title=candidate.document.title,
        )
        run_id = str(query.get("run_id", "web-content"))
        observations: list[EvidenceObservation] = []
        for index, (start, passage, mentioned) in enumerate(passages):
            quote = bounded_quote(passage)
            observations.append(
                EvidenceObservation(
                    idempotency_key=(
                        f"{self.name}:v3:{content_hash}:{candidate.observation_id}:{index}"
                    ),
                    document=document,
                    mentioned_entity_ids=(
                        candidate.document.issuer_entity_id,
                        *(
                            entity
                            for entity in mentioned
                            if entity != candidate.document.issuer_entity_id
                        ),
                    ),
                    payload=TextEvidence(
                        text=passage,
                        exact_quote=quote,
                        character_start=start,
                        character_end=start + len(passage),
                        section="fetched_discovery_passage",
                    ),
                    extraction=ExtractionProvenance(
                        extractor_name=self.name, extractor_version="3", run_id=run_id
                    ),
                )
            )
        return observations

    def _fetch(self, original_url: str) -> tuple[bytes, str]:
        current_url = original_url
        for _ in range(self._maximum_redirects + 1):
            response = self._client.get(current_url, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect response did not include a location")
                current_url = urljoin(current_url, location)
                if not self._policy.allows(current_url):
                    raise ValueError("redirect target is not in the reviewed web-fetch allow-list")
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and not any(
                kind in content_type for kind in ("text/html", "text/plain")
            ):
                raise ValueError("fetched content is not HTML or plain text")
            raw = response.content
            if len(raw) > self._maximum_bytes:
                raise ValueError("fetched page exceeds maximum allowed byte size")
            return raw, current_url
        raise ValueError("redirect limit exceeded")

    def _cache_raw(self, content_hash: str, raw: bytes) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{content_hash}.html").write_bytes(raw)

    @staticmethod
    def _aliases(raw_aliases: Mapping[object, object]) -> dict[str, tuple[str, ...]]:
        aliases: dict[str, tuple[str, ...]] = {}
        for entity_id, values in raw_aliases.items():
            if not isinstance(entity_id, str) or not isinstance(values, list):
                raise ValueError("entity_aliases must map strings to string lists")
            clean = tuple(value.lower() for value in values if isinstance(value, str) and value)
            if clean:
                aliases[entity_id] = clean
        if not aliases:
            raise ValueError("entity_aliases must contain at least one approved entity")
        return aliases

    @staticmethod
    def _rank_passages(
        text: str, aliases: dict[str, tuple[str, ...]], *, max_passages: int
    ) -> list[tuple[int, str, tuple[str, ...]]]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        candidates: list[tuple[int, int, str, tuple[str, ...]]] = []
        offset = 0
        for index in range(len(sentences)):
            window = " ".join(sentences[index : index + 4]).strip()
            sentence = sentences[index]
            start = text.find(sentence, offset)
            offset = max(offset, start + len(sentence))
            if not window or start < 0:
                continue
            lower = window.lower()
            mentioned = tuple(
                entity_id
                for entity_id, entity_aliases in aliases.items()
                if any(alias in lower for alias in entity_aliases)
            )
            relationship_hits = sum(term in lower for term in _RELATIONSHIP_TERMS)
            score = 5 * len(mentioned) + 2 * relationship_hits
            if len(mentioned) < 2 or relationship_hits == 0:
                continue
            candidates.append((score, start, window[:1_600], mentioned))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected: list[tuple[int, str, tuple[str, ...]]] = []
        for _, start, passage, mentioned in candidates:
            if all(abs(start - prior_start) > 500 for prior_start, _, _ in selected):
                selected.append((start, passage, mentioned))
            if len(selected) == max_passages:
                break
        return selected
