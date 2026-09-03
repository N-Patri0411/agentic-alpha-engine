"""Conservative SEC EDGAR filing metadata and document snapshot adapter."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ..evidence import (
    DuckDBEvidenceLedger,
    EvidenceObservation,
    EvidenceRunReceipt,
    SourceDocument,
    TextEvidence,
)
from ..evidence.contracts import ExtractionProvenance
from ..extraction.sections import FilingSectionSelector
from ..settings import required_setting
from .base import AdapterHealth, SourceSnapshot
from .primary_documents import bounded_quote

_SUPPORTED_FORMS = {"10-K", "10-Q", "8-K", "20-F", "6-K"}
_EXHIBIT_NAME = re.compile(r"(?:^|[-_.])ex(?:hibit)?[-_.]?99", re.IGNORECASE)


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
        requested_forms = query.get("forms", ["10-K", "10-Q", "8-K", "20-F", "6-K"])
        if not isinstance(requested_forms, list):
            raise ValueError("forms must be a list")
        forms = {str(form) for form in requested_forms}
        unsupported = forms - _SUPPORTED_FORMS
        if unsupported:
            raise ValueError(f"unsupported SEC forms: {sorted(unsupported)}")
        max_filings_value = query.get("max_filings")
        max_filings: int | None = None
        if max_filings_value is not None:
            max_filings = int(str(max_filings_value))
            if max_filings < 1:
                raise ValueError("max_filings must be at least 1")
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
            filing = {
                "cik": cik,
                "form": form,
                "accession_number": accession,
                "filing_date": recent["filingDate"][index],
                "source_url": url,
                "document_kind": "primary_filing",
            }
            filings.append(filing)
            if max_filings is not None and len(filings) >= max_filings:
                break
        if bool(query.get("include_exhibits", False)):
            expanded: list[dict[str, object]] = []
            for filing in filings:
                expanded.append(filing)
                expanded.extend(self._discover_relevant_exhibits(filing))
            return expanded
        return filings

    def fetch(
        self, identifier: str, *, available_at: datetime | None = None
    ) -> SourceSnapshot:
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
            available_at=available_at or now,
            content_sha256=digest,
            usage_note="SEC public filing; cached locally",
        )

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        """Collect SEC passages as common source evidence without graph inference.

        Required query keys are ``cik`` and ``issuer_entity_id``. Optional
        ``forms``, ``include_exhibits``, ``max_filings`` and ``max_passages``
        bound work explicitly so a nightly run cannot fan out unexpectedly.
        """

        issuer_entity_id = str(query.get("issuer_entity_id", ""))
        if not issuer_entity_id:
            raise ValueError("issuer_entity_id is required")
        max_filings = int(str(query.get("max_filings", 5)))
        max_passages = int(str(query.get("max_passages", 3)))
        if max_filings < 1 or max_passages < 1:
            raise ValueError("max_filings and max_passages must both be at least 1")
        run_id = str(query.get("run_id", "sec-collection"))
        # Discover only primary documents first, then inspect exhibits for the
        # bounded selection. This avoids index requests for every historical filing.
        discovery_query = {**query, "include_exhibits": False, "max_filings": max_filings}
        filings = self.discover(discovery_query)[:max_filings]
        if bool(query.get("include_exhibits", False)):
            expanded: list[dict[str, object]] = []
            for filing in filings:
                expanded.append(filing)
                expanded.extend(self._discover_relevant_exhibits(filing))
            filings = expanded
        selector = FilingSectionSelector()
        observations: list[EvidenceObservation] = []
        for filing in filings:
            filing_date = self._filing_time(str(filing["filing_date"]))
            snapshot = self.fetch(str(filing["source_url"]), available_at=filing_date)
            cached_html = self._cache_dir / f"{snapshot.content_sha256}.html"
            passages = selector.select(cached_html, snapshot, max_passages=max_passages)
            for index, passage in enumerate(passages):
                quote = bounded_quote(passage.text)
                document = SourceDocument(
                    source_kind="sec_filing",
                    source_tier="primary",
                    source_adapter=self.name,
                    source_url=str(filing["source_url"]),
                    content_sha256=snapshot.content_sha256,
                    issuer_entity_id=issuer_entity_id,
                    observed_at=filing_date,
                    available_at=filing_date,
                    retrieved_at=snapshot.retrieved_at,
                    usage_note=(
                        "SEC public filing; use filing date as conservative availability time"
                    ),
                    external_id=str(filing["accession_number"]),
                    title=f"{filing['form']} {filing['document_kind']}",
                )
                key_material = (
                    f"{snapshot.content_sha256}:{filing['accession_number']}:"
                    f"{filing['document_kind']}:{index}:{passage.start_offset}:{quote}"
                )
                observations.append(
                    EvidenceObservation(
                        idempotency_key=(
                            "sec:" + hashlib.sha256(key_material.encode("utf-8")).hexdigest()
                        ),
                        document=document,
                        mentioned_entity_ids=(issuer_entity_id,),
                        payload=TextEvidence(
                            text=passage.text,
                            exact_quote=quote,
                            character_start=0,
                            character_end=len(quote),
                            section="ranked_filing_passage",
                        ),
                        extraction=ExtractionProvenance(
                            extractor_name=self.name, extractor_version="1", run_id=run_id
                        ),
                    )
                )
        return observations

    def collect_and_record(
        self, query: dict[str, object], ledger: DuckDBEvidenceLedger
    ) -> EvidenceRunReceipt:
        """Collect evidence and persist an append-only receipt to the shared ledger."""

        started_at = datetime.now(UTC)
        observations = self.collect(query)
        ledger.append_many(observations)
        finished_at = datetime.now(UTC)
        run_id = str(query.get("run_id", "sec-collection"))
        receipt_material = ":".join([run_id, *(item.idempotency_key for item in observations)])
        receipt = EvidenceRunReceipt(
            idempotency_key=(
                "sec-receipt:" + hashlib.sha256(receipt_material.encode("utf-8")).hexdigest()
            ),
            run_id=run_id,
            adapter_name=self.name,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            observation_idempotency_keys=tuple(item.idempotency_key for item in observations),
        )
        ledger.append_run_receipt(receipt)
        return receipt

    def normalize(self, snapshot: SourceSnapshot) -> list[dict[str, object]]:
        return [{"snapshot_sha256": snapshot.content_sha256, "source_url": snapshot.source_url}]

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=False)

    def _discover_relevant_exhibits(self, filing: dict[str, object]) -> list[dict[str, object]]:
        """Return selected public exhibits, presently earnings-release EX-99 files.

        EDGAR's filing index is the authoritative per-filing file listing. We
        deliberately limit the initial selector to EX-99-style exhibits instead
        of treating every attachment as research evidence.
        """

        cik = str(filing["cik"])
        accession = str(filing["accession_number"])
        archive_path = accession.replace("-", "")
        index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{archive_path}/index.json"
        payload: dict[str, Any] = self._get(index_url).json()
        items = payload.get("directory", {}).get("item", [])
        documents: list[dict[str, object]] = []
        for item in items:
            name = str(item.get("name", ""))
            if not _EXHIBIT_NAME.search(name):
                continue
            documents.append(
                {
                    **filing,
                    "source_url": (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{archive_path}/{name}"
                    ),
                    "document_kind": "exhibit_99",
                }
            )
        return documents

    @staticmethod
    def _filing_time(value: str) -> datetime:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
