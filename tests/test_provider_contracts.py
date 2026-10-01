from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from alpha_workbench.adapters.alpha_vantage import AlphaVantageDailyAdapter
from alpha_workbench.providers.alpha_vantage_compat import AlphaVantageCompatibilityAdapter
from alpha_workbench.providers.contracts import (
    CoverageReport,
    DataChronology,
    HistoricalBar,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    IdentifierMappingRequest,
    InstrumentQuery,
    InstrumentRecord,
    ProviderProvenance,
)
from alpha_workbench.providers.eodhd import EodhdAdapter
from alpha_workbench.providers.openfigi import OpenFigiAdapter
from alpha_workbench.providers.registry import ProviderRegistry, build_provider

FIXTURES = Path(__file__).parent / "fixtures" / "providers"
NOW = datetime.now(UTC) + timedelta(days=1)


def test_contract_rejects_naive_time_and_future_available_data() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        IdentifierMappingRequest(
            identifier_type="symbol",
            identifier_value="ABC",
            exchange="US",
            as_of_time=datetime(2026, 9, 30),
        )

    instrument = InstrumentRecord(symbol="ABC", exchange="US")
    bar = HistoricalBar(
        instrument=instrument,
        start=NOW - timedelta(days=1),
        end=NOW,
        open=10,
        high=11,
        low=9,
        close=10,
        volume=100,
        chronology=DataChronology(
            observed_at=NOW,
            available_at=NOW + timedelta(seconds=1),
            as_of_time=NOW,
        ),
    )
    with pytest.raises(ValueError, match="unavailable"):
        HistoricalBarsResult(
            items=(bar,),
            coverage=CoverageReport(
                capability="historical_bars", status="complete", requested_count=1, returned_count=1
            ),
            provenance=ProviderProvenance(provider_id="test", request_id="r1", retrieved_at=NOW),
            as_of_time=NOW,
        )


def test_openfigi_reports_ambiguous_symbol_without_exchange() -> None:
    payload = json.loads((FIXTURES / "openfigi_two_listings.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/mapping"
        return httpx.Response(200, json=payload)

    adapter = OpenFigiAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = adapter.map_identifier(
        IdentifierMappingRequest(
            identifier_type="symbol",
            identifier_value="ACME",
            exchange="US",
            as_of_time=NOW,
        )
    )
    # The frozen response includes two listings; explicit exchange is applied before ambiguity.
    assert result.coverage.status == "complete"
    assert result.items[0].figi == "BBG000B9XRY4"

    result = adapter.map_identifier(
        IdentifierMappingRequest(
            identifier_type="symbol",
            identifier_value="ACME",
            as_of_time=NOW,
        )
    )
    assert result.coverage.status == "missing"
    assert "exchange" in result.coverage.detail

    assert "instrument_discovery" not in adapter.capability.capabilities
    discovery = adapter.discover_instruments(
        InstrumentQuery(query="semiconductors", as_of_time=NOW)
    )
    assert discovery.coverage.status == "unsupported"


def test_eodhd_bars_use_frozen_fixture_and_enforce_as_of() -> None:
    payload = json.loads((FIXTURES / "eodhd_daily.json").read_text())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    adapter = EodhdAdapter(
        api_key="fixture-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://fixture.invalid/api",
    )
    request = HistoricalBarsRequest(
        instrument=InstrumentRecord(symbol="ABC", exchange="US"),
        start=date(2026, 9, 28),
        end=date(2026, 9, 28),
        as_of_time=NOW + timedelta(days=1),
    )
    result = adapter.historical_bars(request)
    assert len(result.items) == 1
    assert result.items[0].close == 104
    assert result.provenance.source_url == "https://fixture.invalid/api/eod/ABC.US"
    assert "fixture-secret" not in result.model_dump_json()
    assert captured[0].url.params["api_token"] == "fixture-secret"

    expired = adapter.historical_bars(
        request.model_copy(update={"as_of_time": NOW - timedelta(days=1)})
    )
    assert expired.items == ()
    assert expired.coverage.status == "missing"


def test_eodhd_global_search_discovery_keeps_exchange_listings_distinct() -> None:
    payload = json.loads((FIXTURES / "eodhd_search.json").read_text())
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.path == "/api/search/Acme Corporation"
        return httpx.Response(200, json=payload)

    adapter = EodhdAdapter(
        api_key="fixture-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        base_url="https://fixture.invalid/api",
    )
    result = adapter.discover_instruments(
        InstrumentQuery(query="Acme Corporation", as_of_time=datetime.now(UTC) + timedelta(days=1))
    )
    assert [(item.symbol, item.exchange) for item in result.items] == [
        ("ACME", "US"),
        ("ACME", "LSE"),
    ]
    assert result.coverage.status == "complete"
    assert "fixture-secret" not in result.model_dump_json()


def test_alpha_vantage_compatibility_uses_frozen_fixture() -> None:
    payload = (FIXTURES / "alpha_vantage_daily.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.alphavantage.co"
        return httpx.Response(200, content=payload)

    legacy_adapter = AlphaVantageDailyAdapter(
        api_key="fixture-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval_seconds=0,
        now=lambda: datetime.now(UTC),
    )
    adapter = AlphaVantageCompatibilityAdapter(adapter=legacy_adapter)
    result = adapter.historical_bars(
        HistoricalBarsRequest(
            instrument=InstrumentRecord(symbol="NVDA", exchange="US"),
            start=date(2026, 1, 5),
            end=date(2026, 1, 6),
            as_of_time=datetime.now(UTC) + timedelta(days=1),
        )
    )
    assert len(result.items) == 2
    assert result.items[0].close == 153
    assert result.coverage.status == "complete"
    assert "fixture-secret" not in result.model_dump_json()


def test_registry_and_factory_use_configured_adapters_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    provider = build_provider("openfigi", config_path=Path("config/providers/catalog.yaml"))
    registry = ProviderRegistry((provider,))
    assert registry.get("openfigi").capability.provider_id == "openfigi"
    assert registry.list_capabilities()[0].capabilities == ("identifier_mapping",)

    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    catalog_registry = ProviderRegistry.from_config("config/providers/catalog.yaml")
    catalog = {entry.capability.provider_id: entry for entry in catalog_registry.list_catalog()}
    assert catalog["openfigi"].configured is True
    assert catalog["eodhd"].configured is False
    assert catalog["eodhd"].credentials_env == "EODHD_API_KEY"
    assert "eodhd" not in catalog_registry.configured_provider_ids
