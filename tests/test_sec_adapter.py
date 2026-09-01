from pathlib import Path

import httpx

from alpha_workbench.adapters import SecFilingAdapter


def test_sec_adapter_discovers_and_caches_a_frozen_document(tmp_path: Path) -> None:
    metadata = {"filings": {"recent": {
        "form": ["10-K", "8-K"],
        "accessionNumber": ["0001-24-000001", "x"],
        "primaryDocument": ["annual.htm", "other.htm"],
        "filingDate": ["2024-02-01", "2024-03-01"],
    }}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "data.sec.gov":
            return httpx.Response(200, json=metadata)
        return httpx.Response(200, content=b"<html>fixture filing</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SecFilingAdapter(tmp_path, user_agent="Test test@example.com", client=client)
    filings = adapter.discover({"cik": "1045810", "forms": ["10-K"]})
    assert filings[0]["form"] == "10-K"
    snapshot = adapter.fetch(str(filings[0]["source_url"]))
    assert snapshot.source_url == filings[0]["source_url"]
    assert (tmp_path / f"{snapshot.content_sha256}.html").exists()
