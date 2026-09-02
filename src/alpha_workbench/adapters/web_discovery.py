"""Provider-neutral web discovery and corroboration intake.

Discovery observations are intentionally lower-tier inputs. This adapter has no
graph imports and no publishing operation: it can only record candidate
documents for later evidence validation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field, HttpUrl, field_validator

from ..evidence import EvidenceObservation, SourceDocument, TextEvidence
from ..evidence.contracts import ExtractionProvenance
from .base import AdapterHealth


class DiscoveryResult(BaseModel):
    """A result returned by an injected search provider or supplied by a caller."""

    source_url: HttpUrl
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    published_at: datetime
    mentioned_entity_ids: tuple[str, ...] = ()

    @field_validator("published_at")
    @classmethod
    def _published_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("published_at must include a timezone")
        return value


class DiscoverySearchBackend(Protocol):
    """Optional provider implementation; vendor adapters live outside agents."""

    def search(self, query: str) -> list[DiscoveryResult]: ...


class WebDiscoveryAdapter:
    """Normalize discovery/corroboration results to immutable observations only."""

    name = "web_discovery"
    requires_api_key = False

    def __init__(
        self,
        *,
        search_backend: DiscoverySearchBackend | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._search_backend = search_backend
        self._now = now or (lambda: datetime.now(UTC))

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        issuer_entity_id = str(query["issuer_entity_id"])
        if not issuer_entity_id:
            raise ValueError("issuer_entity_id is required")
        supplied_results = query.get("results")
        if supplied_results is None:
            query_text = query.get("query")
            if not isinstance(query_text, str) or not query_text:
                raise ValueError("query is required when results are not supplied")
            if self._search_backend is None:
                raise RuntimeError("no discovery search backend is configured")
            results = self._search_backend.search(query_text)
        else:
            if not isinstance(supplied_results, list):
                raise ValueError("results must be a list")
            results = [DiscoveryResult.model_validate(item) for item in supplied_results]
        run_id = str(query.get("run_id", "web-discovery"))
        retrieved_at = self._now()
        observations: list[EvidenceObservation] = []
        for result in results:
            payload_text = f"{result.title}\n{result.summary}"
            content_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            mentioned = (issuer_entity_id,) + tuple(
                entity for entity in result.mentioned_entity_ids if entity != issuer_entity_id
            )
            document = SourceDocument(
                source_kind="web_discovery",
                source_tier="discovery",
                source_adapter=self.name,
                source_url=str(result.source_url),
                content_sha256=content_sha256,
                issuer_entity_id=issuer_entity_id,
                observed_at=result.published_at,
                available_at=result.published_at,
                retrieved_at=retrieved_at,
                usage_note=(
                    "Discovery/corroboration result; never sufficient alone for graph publication"
                ),
                title=result.title,
            )
            observations.append(
                EvidenceObservation(
                    idempotency_key=f"{self.name}:{issuer_entity_id}:{content_sha256}",
                    document=document,
                    mentioned_entity_ids=mentioned,
                    payload=TextEvidence(
                        text=payload_text,
                        exact_quote=result.summary,
                        character_start=len(result.title) + 1,
                        character_end=len(payload_text),
                        section="search_result_summary",
                    ),
                    extraction=ExtractionProvenance(
                        extractor_name=self.name,
                        extractor_version="1",
                        run_id=run_id,
                    ),
                )
            )
        return observations
