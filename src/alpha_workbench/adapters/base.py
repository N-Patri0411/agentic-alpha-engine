"""Common interface for every current and future source adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class SourceSnapshot(BaseModel):
    source: str
    retrieved_at: datetime
    observed_at: datetime
    available_at: datetime
    content_sha256: str
    usage_note: str


class AdapterHealth(BaseModel):
    adapter: str
    implemented: bool
    requires_api_key: bool


class SourceAdapter(Protocol):
    name: str

    def discover(self, query: dict[str, object]) -> list[dict[str, object]]: ...

    def fetch(self, identifier: str) -> SourceSnapshot: ...

    def normalize(self, snapshot: SourceSnapshot) -> list[dict[str, object]]: ...

    def health_check(self) -> AdapterHealth: ...


class StubAdapter:
    name: str
    requires_api_key = False

    def discover(self, query: dict[str, object]) -> list[dict[str, object]]:
        del query
        raise NotImplementedError(f"{self.name} is a declared adapter, not implemented yet")

    def fetch(self, identifier: str) -> SourceSnapshot:
        del identifier
        raise NotImplementedError(f"{self.name} is a declared adapter, not implemented yet")

    def normalize(self, snapshot: SourceSnapshot) -> list[dict[str, object]]:
        del snapshot
        raise NotImplementedError(f"{self.name} is a declared adapter, not implemented yet")

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            adapter=self.name, implemented=False, requires_api_key=self.requires_api_key
        )


class SecFilingAdapter(StubAdapter):
    name = "sec_filings"


class MarketDataAdapter(StubAdapter):
    name = "market_data"
    requires_api_key = True


class InvestorRelationsAdapter(StubAdapter):
    name = "investor_relations"


class EarningsCallAdapter(StubAdapter):
    name = "earnings_calls"


class PatentRegulatoryAdapter(StubAdapter):
    name = "patent_regulatory"


class JobPostingAdapter(StubAdapter):
    name = "job_postings"


class ResearchWebAdapter(StubAdapter):
    name = "research_web"
