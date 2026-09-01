"""Conservative SEC EDGAR filing metadata and document snapshot adapter."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..settings import required_setting
from .base import AdapterHealth, SourceSnapshot


class SecFilingAdapter:
    name = "sec_filings"
    requires_api_key = False

    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str | None = None,
        min_interval_seconds: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._user_agent = user_agent or required_setting("SEC_USER_AGENT")
        self._min_interval_seconds = min_interval_seconds
        self._client = client or httpx.Client(
            timeout=20.0, headers={"User-Agent": self._user_agent}
        )
        self._last_request_at = 0.0

    def _get(self, url: str) -> httpx.Response:
        remaining = self._min_interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        response = self._client.get(url, headers={"User-Agent": self._user_agent})
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response

    def discover(self, query: dict[str, object]) -> list[dict[str, object]]:
        cik = str(query["cik"]).zfill(10)
        requested_forms = query.get("forms", ["10-K", "10-Q", "20-F", "6-K"])
        if not isinstance(requested_forms, list):
            raise ValueError("forms must be a list")
        forms = {str(form) for form in requested_forms}
        payload: dict[str, Any] = self._get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        recent = payload.get("filings", {}).get("recent", {})
        filings: list[dict[str, object]] = []
        for index, form in enumerate(recent.get("form", [])):
            if form not in forms:
                continue
            accession = str(recent["accessionNumber"][index])
            primary_document = str(recent["primaryDocument"][index])
            accession_path = accession.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_document}"
            filings.append({"cik": cik, "form": form, "accession_number": accession,
                            "filing_date": recent["filingDate"][index], "source_url": url})
        return filings

    def fetch(self, identifier: str) -> SourceSnapshot:
        response = self._get(identifier)
        content = response.content
        digest = hashlib.sha256(content).hexdigest()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{digest}.html").write_bytes(content)
        now = datetime.now(UTC)
        return SourceSnapshot(
            source=self.name,
            source_url=identifier,
            retrieved_at=now,
            observed_at=now,
            available_at=now,
            content_sha256=digest,
            usage_note="SEC public filing; cached locally",
        )

    def normalize(self, snapshot: SourceSnapshot) -> list[dict[str, object]]:
        return [{"snapshot_sha256": snapshot.content_sha256, "source_url": snapshot.source_url}]

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)
