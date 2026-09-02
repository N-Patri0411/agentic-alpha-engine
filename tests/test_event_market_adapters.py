from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from alpha_workbench.adapters.alpha_vantage import AlphaVantageDailyAdapter
from alpha_workbench.adapters.earnings import OfficialEarningsEvidenceAdapter
from alpha_workbench.adapters.rate_limit import RequestPacer
from alpha_workbench.adapters.web_discovery import DiscoveryResult, WebDiscoveryAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "event_market"
NOW = datetime(2026, 1, 10, 12, tzinfo=UTC)


def _client_for(content: bytes, *, status_code: int = 200) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code, content=content))
    )


def test_official_earnings_adapter_emits_common_text_evidence() -> None:
    content = (FIXTURES / "earnings_release.html").read_bytes()
    adapter = OfficialEarningsEvidenceAdapter(client=_client_for(content), now=lambda: NOW)

    observations = adapter.collect(
        {
            "run_id": "earnings-fixture",
            "documents": [
                {
                    "issuer_entity_id": "NVDA",
                    "source_url": "https://investor.example.test/results",
                    "published_at": "2026-01-08T12:00:00+00:00",
                    "kind": "official_press_release",
                    "title": "Quarterly results",
                    "mentioned_entity_ids": ["TSM"],
                }
            ],
        }
    )

    assert len(observations) == 1
    observation = observations[0]
    assert observation.document.source_kind == "investor_relations"
    assert observation.document.source_tier == "official"
    assert observation.mentioned_entity_ids == ("NVDA", "TSM")
    assert "accelerated computing" in observation.payload.text
    assert "ignore me" not in observation.payload.text
    assert observation.document.available_at == datetime(2026, 1, 8, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("kind", "expected_kind", "expected_tier"),
    [
        ("official_transcript", "earnings_call", "official"),
        ("official_webcast", "earnings_call", "official"),
        ("sec_8k_exhibit", "sec_filing", "primary"),
    ],
)
def test_earnings_fallbacks_preserve_source_classification(
    kind: str, expected_kind: str, expected_tier: str
) -> None:
    adapter = OfficialEarningsEvidenceAdapter(
        client=_client_for(b"Official earnings evidence."), now=lambda: NOW
    )
    observations = adapter.collect(
        {
            "documents": [
                {
                    "issuer_entity_id": "AMD",
                    "source_url": "https://example.test/document",
                    "published_at": "2026-01-08T12:00:00+00:00",
                    "kind": kind,
                }
            ]
        }
    )
    assert observations[0].document.source_kind == expected_kind
    assert observations[0].document.source_tier == expected_tier


def test_official_earnings_adapter_reports_http_error_without_retrying() -> None:
    adapter = OfficialEarningsEvidenceAdapter(client=_client_for(b"not found", status_code=404))
    with pytest.raises(httpx.HTTPStatusError):
        adapter.collect(
            {
                "documents": [
                    {
                        "issuer_entity_id": "NVDA",
                        "source_url": "https://example.test/missing",
                        "published_at": "2026-01-08T12:00:00+00:00",
                        "kind": "official_transcript",
                    }
                ]
            }
        )


def test_request_pacer_enforces_minimum_interval() -> None:
    elapsed = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        elapsed[0] += seconds

    pacer = RequestPacer(5.0, clock=lambda: elapsed[0], sleeper=sleep)
    pacer.wait()
    elapsed[0] += 1.0
    pacer.wait()
    assert waits == [4.0]


def test_web_discovery_records_lower_tier_evidence_without_graph_output() -> None:
    adapter = WebDiscoveryAdapter(now=lambda: NOW)
    observations = adapter.collect(
        {
            "issuer_entity_id": "NVDA",
            "run_id": "discovery-fixture",
            "results": [
                {
                    "source_url": "https://news.example.test/article",
                    "title": "Report on semiconductor capacity",
                    "summary": "The report describes supplier capacity constraints.",
                    "published_at": "2026-01-09T12:00:00+00:00",
                    "mentioned_entity_ids": ["TSM"],
                }
            ],
        }
    )
    observation = observations[0]
    assert observation.document.source_tier == "discovery"
    assert observation.document.source_kind == "web_discovery"
    assert observation.mentioned_entity_ids == ("NVDA", "TSM")
    assert not hasattr(adapter, "publish")


def test_web_discovery_uses_injected_backend_and_requires_one_when_results_missing() -> None:
    class Backend:
        def search(self, query: str) -> list[DiscoveryResult]:
            assert query == "NVIDIA supply chain"
            return [
                DiscoveryResult(
                    source_url="https://news.example.test/article",
                    title="Result",
                    summary="A corroborating report.",
                    published_at=datetime(2026, 1, 9, tzinfo=UTC),
                )
            ]

    adapter = WebDiscoveryAdapter(search_backend=Backend(), now=lambda: NOW)
    assert len(adapter.collect({"issuer_entity_id": "NVDA", "query": "NVIDIA supply chain"})) == 1
    with pytest.raises(RuntimeError, match="no discovery search backend"):
        WebDiscoveryAdapter(now=lambda: NOW).collect(
            {"issuer_entity_id": "NVDA", "query": "NVIDIA supply chain"}
        )


def test_alpha_vantage_daily_adapter_emits_development_only_market_bars() -> None:
    payload = (FIXTURES / "alpha_vantage_daily.json").read_bytes()
    adapter = AlphaVantageDailyAdapter(
        api_key="fixture-key",
        client=_client_for(payload),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    observations = adapter.collect(
        {"issuer_entity_id": "NVDA", "symbol": "nvda", "run_id": "market-fixture"}
    )

    assert [item.payload.symbol for item in observations] == ["NVDA", "NVDA"]
    assert observations[0].payload.close == 153.0
    assert observations[0].document.available_at == NOW
    assert "point-in-time" in observations[0].document.usage_note
    assert "fixture-key" not in observations[0].document.source_url


@pytest.mark.parametrize(
    "payload",
    [
        {"Note": "API call frequency is 5 calls per minute."},
        {"Error Message": "Invalid API call."},
        {"Time Series (Daily)": {"2026-01-05": {"1. open": "bad"}}},
    ],
)
def test_alpha_vantage_provider_and_data_errors_are_not_silently_normalized(
    payload: dict[str, object]
) -> None:
    adapter = AlphaVantageDailyAdapter(
        api_key="fixture-key",
        client=_client_for(json.dumps(payload).encode("utf-8")),
        min_interval_seconds=0,
        now=lambda: NOW,
    )
    with pytest.raises((RuntimeError, ValueError)):
        adapter.collect({"issuer_entity_id": "NVDA", "symbol": "NVDA"})
