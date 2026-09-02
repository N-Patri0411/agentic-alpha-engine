"""Read the tracked allow-list of official primary sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CatalogSource(BaseModel):
    """One configured source. URLs are reviewed repository configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_entity_id: str = Field(min_length=1)
    source_kind: Literal["sec_filings", "investor_relations"]
    url: str = Field(min_length=1)
    cik: str | None = None
    format: Literal["html_page", "rss", "atom", "presentation"] = "html_page"
    polling_hint: Literal["event_driven", "nightly", "quarterly", "manual"] = "nightly"
    usage_note: str = Field(min_length=1)


class SourceCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: str = Field(min_length=1)
    schema_version: Literal["1"] = "1"
    sources: tuple[CatalogSource, ...] = Field(min_length=1)

    def for_adapter(
        self, source_kind: Literal["sec_filings", "investor_relations"]
    ) -> tuple[CatalogSource, ...]:
        return tuple(source for source in self.sources if source.source_kind == source_kind)


def load_source_catalog(path: Path) -> SourceCatalog:
    """Load a repository-tracked allow-list; never discover arbitrary URLs."""

    return SourceCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
