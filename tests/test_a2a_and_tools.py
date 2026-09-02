from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_workbench.a2a import A2AMessage, DuckDBMessageBus
from alpha_workbench.adapters import MarketDataAdapter, SecFilingAdapter
from alpha_workbench.tools import CapabilityManifest, ToolRegistry


def test_message_bus_delivers_and_acknowledges_once(tmp_path: Path) -> None:
    bus = DuckDBMessageBus(tmp_path / "messages.duckdb")
    message = A2AMessage(
        trace_id="trace-1", run_id="run-1", sender="orchestrator", recipient="extraction",
        message_type="command", created_at=datetime.now(UTC), idempotency_key="key-1",
    )
    assert bus.publish(message) is True
    assert bus.publish(message) is False
    assert bus.inbox("extraction")[0].message_id == message.message_id
    bus.acknowledge(str(message.message_id))
    assert bus.inbox("extraction") == []


def test_registry_only_resolves_explicitly_granted_tools() -> None:
    manifest = CapabilityManifest.from_yaml(Path("config/agent_capabilities.yaml"))
    registry = ToolRegistry()
    for name in manifest.tools_for("extraction"):
        registry.register(name, lambda payload: payload)
    extraction_tools = registry.resolve("extraction", manifest)
    assert "sec_filings" in extraction_tools
    assert "market_data" in extraction_tools
    with pytest.raises(ValueError, match="unregistered tools"):
        registry.resolve("backtester", manifest)


def test_future_adapters_are_declared_but_not_implemented(tmp_path: Path) -> None:
    sec = SecFilingAdapter(tmp_path, user_agent="Test test@example.com")
    assert sec.health_check().implemented is True
    assert MarketDataAdapter().health_check().requires_api_key is True
    with pytest.raises(NotImplementedError):
        MarketDataAdapter().discover({"entity": "TSM"})
