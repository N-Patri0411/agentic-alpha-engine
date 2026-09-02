from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from alpha_workbench.adapters.earnings import SecEarningsDocumentDiscoverer
from alpha_workbench.adapters.investor_relations import OfficialInvestorRelationsAdapter
from alpha_workbench.adapters.sec import SecFilingAdapter
from alpha_workbench.adapters.source_catalog import CatalogSource, load_source_catalog
from alpha_workbench.evidence import DuckDBEvidenceLedger


def test_sec_collection_supports_all_initial_forms_and_exhibit_99(tmp_path: Path) -> None:
    metadata = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "8-K", "20-F", "6-K"],
                "accessionNumber": [
                    "0001-26-000001",
                    "0001-26-000002",
                    "0001-26-000003",
                    "0001-26-000004",
                    "0001-26-000005",
                ],
                "primaryDocument": [
                    "annual.htm",
                    "quarter.htm",
                    "event.htm",
                    "foreign.htm",
                    "report.htm",
                ],
                "filingDate": [
                    "2026-01-01",
                    "2026-02-01",
                    "2026-03-01",
                    "2026-04-01",
                    "2026-05-01",
                ],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data.sec.gov":
            return httpx.Response(200, json=metadata)
        if request.url.path.endswith("index.json"):
            return httpx.Response(
                200,
                json={
                    "directory": {
                        "item": [{"name": "company-ex99.1.htm"}, {"name": "readme.txt"}]
                    }
                },
            )
        return httpx.Response(
            200,
            content=(
                b"<html><body><p>We rely on TSMC manufacturing capacity and maintain "
                b"supply agreements for leading products.</p></body></html>"
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SecFilingAdapter(tmp_path / "sec", user_agent="Test test@example.com", client=client)
    discovered = adapter.discover(
        {"cik": "1045810", "forms": ["10-K", "10-Q", "8-K", "20-F", "6-K"]}
    )
    assert {str(item["form"]) for item in discovered} == {"10-K", "10-Q", "8-K", "20-F", "6-K"}

    observations = adapter.collect(
        {
            "cik": "1045810",
            "issuer_entity_id": "NVDA",
            "forms": ["8-K"],
            "include_exhibits": True,
            "max_filings": 2,
            "max_passages": 1,
            "run_id": "fixture-sec-run",
        }
    )

    assert len(observations) == 2
    assert {item.document.title for item in observations} == {
        "8-K primary_filing",
        "8-K exhibit_99",
    }
    assert all(item.document.external_id == "0001-26-000003" for item in observations)
    assert all(
        item.document.available_at == datetime(2026, 3, 1, tzinfo=UTC)
        for item in observations
    )
    assert all(item.payload.payload_type == "text" for item in observations)


def test_sec_collection_persists_idempotent_evidence_and_receipt(tmp_path: Path) -> None:
    metadata = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0001-26-000001"],
                "primaryDocument": ["annual.htm"],
                "filingDate": ["2026-01-01"],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data.sec.gov":
            return httpx.Response(200, json=metadata)
        return httpx.Response(
            200,
            content=b"<p>We utilize a single source foundry and monitor capacity.</p>",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SecFilingAdapter(tmp_path / "sec", user_agent="Test test@example.com", client=client)
    ledger = DuckDBEvidenceLedger(tmp_path / "ledger.duckdb")
    query = {"cik": "1045810", "issuer_entity_id": "NVDA", "run_id": "sec-receipt"}
    receipt = adapter.collect_and_record(query, ledger)
    adapter.collect_and_record(query, ledger)

    assert receipt.status == "completed"
    assert ledger.count_observations() == 1
    ledger.close()


def test_sec_adapter_rejects_forms_outside_the_reviewed_contract(tmp_path: Path) -> None:
    adapter = SecFilingAdapter(
        tmp_path / "sec",
        user_agent="Test test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )
    with pytest.raises(ValueError, match="unsupported SEC forms"):
        adapter.discover({"cik": "1045810", "forms": ["S-1"]})


def test_official_ir_adapter_handles_rss_and_page_without_network(tmp_path: Path) -> None:
    rss = b"""<?xml version=\"1.0\"?>
    <rss><channel><item><title>Capacity update</title>
    <link>https://ir.example.test/release-1</link><guid>release-1</guid>
    <pubDate>Mon, 01 Jun 2026 12:00:00 GMT</pubDate>
    <description><![CDATA[<p>We expanded advanced packaging capacity.</p>]]></description>
    </item></channel></rss>"""
    page = (
        b"<html><body><h1>Official News</h1>"
        b"<p>We announced a supply agreement.</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("feed.xml"):
            return httpx.Response(200, content=rss)
        return httpx.Response(200, content=page)

    adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    observations = adapter.collect(
        {
            "run_id": "ir-fixture-run",
            "sources": [
                CatalogSource(
                    issuer_entity_id="NVDA",
                    source_kind="investor_relations",
                    url="https://ir.example.test/feed.xml",
                    format="rss",
                    usage_note="official fixture feed",
                ),
                CatalogSource(
                    issuer_entity_id="AMD",
                    source_kind="investor_relations",
                    url="https://ir.example.test/news",
                    format="html_page",
                    usage_note="official fixture page",
                ),
            ],
        }
    )

    assert len(observations) == 2
    feed = next(item for item in observations if item.document.issuer_entity_id == "NVDA")
    page_observation = next(
        item for item in observations if item.document.issuer_entity_id == "AMD"
    )
    assert feed.document.available_at == datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert feed.document.source_url == "https://ir.example.test/release-1"
    assert "page timestamp unavailable" in page_observation.document.usage_note
    assert page_observation.payload.exact_quote in page_observation.payload.text


def test_official_ir_adapter_handles_atom_without_network(tmp_path: Path) -> None:
    atom = b"""<?xml version=\"1.0\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <entry><title>Packaging update</title>
      <link href=\"https://ir.example.test/atom-release\" />
      <published>2026-06-02T14:30:00Z</published>
      <summary>We expanded packaging capacity.</summary></entry>
    </feed>"""
    adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=atom))
        ),
    )
    observations = adapter.collect(
        {
            "sources": [
                {
                    "issuer_entity_id": "TSM",
                    "source_kind": "investor_relations",
                    "url": "https://ir.example.test/feed.atom",
                    "format": "atom",
                    "usage_note": "official atom fixture",
                }
            ]
        }
    )

    assert len(observations) == 1
    assert observations[0].document.source_url == "https://ir.example.test/atom-release"
    assert observations[0].document.available_at == datetime(2026, 6, 2, 14, 30, tzinfo=UTC)


def test_official_ir_adapter_collects_bounded_same_site_newsroom_pages(tmp_path: Path) -> None:
    landing_page = b"""
    <html><body><a href="/news/release-one">Release</a>
    <a href="https://untrusted.example.test/news/ignore">Ignore</a></body></html>
    """
    release_page = b"<p>We rely on a strategic foundry partner for manufacturing capacity.</p>"

    def handler(request: httpx.Request) -> httpx.Response:
        content = release_page if request.url.path.endswith("release-one") else landing_page
        return httpx.Response(200, content=content)

    adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    observations = adapter.collect(
        {
            "run_id": "linked-page-fixture",
            "max_linked_pages": 1,
            "sources": [
                {
                    "issuer_entity_id": "NVDA",
                    "source_kind": "investor_relations",
                    "url": "https://ir.example.test/news",
                    "usage_note": "official fixture page",
                }
            ],
        }
    )

    assert len(observations) == 2
    linked = next(item for item in observations if "release-one" in item.document.source_url)
    assert linked.payload.section == "official_linked_newsroom_page"
    assert "rely on" in linked.payload.text


def test_sec_earnings_discoverer_finds_bounded_8k_and_6k_exhibits(tmp_path: Path) -> None:
    metadata = {
        "filings": {
            "recent": {
                "form": ["8-K", "6-K"],
                "accessionNumber": ["0001-26-000001", "0001-26-000002"],
                "primaryDocument": ["event.htm", "foreign.htm"],
                "filingDate": ["2026-01-01", "2026-02-01"],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data.sec.gov":
            return httpx.Response(200, json=metadata)
        if request.url.path.endswith("index.json"):
            return httpx.Response(
                200, json={"directory": {"item": [{"name": "earnings-ex99.htm"}]}}
            )
        return httpx.Response(404)

    sec = SecFilingAdapter(
        tmp_path / "sec", user_agent="Test test@example.com", client=httpx.Client(
            transport=httpx.MockTransport(handler)
        )
    )
    documents = SecEarningsDocumentDiscoverer(sec).discover(
        cik="1045810", issuer_entity_id="NVDA", max_documents=2
    )

    assert [document.kind for document in documents] == ["sec_8k_exhibit", "sec_6k_exhibit"]
    assert all("earnings-ex99.htm" in str(document.source_url) for document in documents)


def test_official_ir_adapter_rejects_malformed_or_unavailable_sources(tmp_path: Path) -> None:
    invalid_adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"not xml"))
        ),
    )
    query = {
        "sources": [
            {
                "issuer_entity_id": "NVDA",
                "source_kind": "investor_relations",
                "url": "https://ir.example.test/feed.xml",
                "format": "rss",
                "usage_note": "official fixture",
            }
        ]
    }
    with pytest.raises(ValueError, match="invalid rss feed"):
        invalid_adapter.collect(query)

    unavailable_adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir-unavailable",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503, content=b"down"))
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        unavailable_adapter.collect(query)


def test_official_ir_receipt_is_idempotent_and_catalog_is_official_allow_list(
    tmp_path: Path,
) -> None:
    adapter = OfficialInvestorRelationsAdapter(
        tmp_path / "ir",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"<p>Official release.</p>")
            )
        ),
    )
    ledger = DuckDBEvidenceLedger(tmp_path / "ledger.duckdb")
    query = {
        "run_id": "ir-receipt",
        "sources": [
            {
                "issuer_entity_id": "NVDA",
                "source_kind": "investor_relations",
                "url": "https://ir.example.test/news",
                "usage_note": "official fixture",
            }
        ],
    }
    adapter.collect_and_record(query, ledger)
    adapter.collect_and_record(query, ledger)
    assert ledger.count_observations() == 1
    ledger.close()

    root = Path(__file__).resolve().parents[1]
    catalog_path = root / "data/source_catalog/semiconductor_primary_sources_v1.json"
    catalog = load_source_catalog(catalog_path)
    assert {source.issuer_entity_id for source in catalog.sources} == {
        "NVDA", "AMD", "TSM", "Samsung", "Hynix", "MU", "GFS", "UMC"
    }
    assert all(source.url.startswith("https://") for source in catalog.sources)
    assert {source.source_kind for source in catalog.sources} == {
        "sec_filings",
        "investor_relations",
    }
