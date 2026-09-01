import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_workbench.graph_registry import (
    EntityRegistry,
    GraphPublisher,
    GraphSnapshot,
    RippleRiskScorer,
)

REGISTRY_PATH = Path("data/entities/semiconductor_v1.json")
SNAPSHOT_PATH = Path("data/graph_snapshots/semiconductor-sec-reviewed-v1.json")


def test_reviewed_snapshot_is_verified_and_scores_in_shock_direction() -> None:
    snapshot = GraphSnapshot.from_json(SNAPSHOT_PATH)
    result = RippleRiskScorer(snapshot).score(
        shock_entity_id="TSM",
        severity=0.9,
        as_of_time=datetime(2026, 5, 1, tzinfo=UTC),
    )

    impacts = {impact.entity: impact for impact in result.impacts}
    assert impacts["AMD"].severity == 0.9 * 0.85 * 0.8
    assert impacts["NVDA"].severity == 0.9 * 0.75 * 0.65
    assert impacts["AMD"].path[0].source == "TSM"
    assert impacts["AMD"].path[0].target == "AMD"


def test_snapshot_rejects_tampered_edge_payload(tmp_path: Path) -> None:
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    payload["edges"][0]["dependency_strength"] = 0.99
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="digest"):
        GraphSnapshot.from_json(tampered)


def test_publisher_rejects_edges_outside_the_entity_registry() -> None:
    registry = EntityRegistry.from_json(REGISTRY_PATH)
    snapshot = GraphSnapshot.from_json(SNAPSHOT_PATH)
    invalid_edge = snapshot.edges[0].model_copy(update={"downstream_entity_id": "UNKNOWN"})

    with pytest.raises(ValueError, match="unregistered"):
        GraphPublisher(registry).build_snapshot(
            snapshot_id="invalid", created_at=datetime(2026, 9, 1, tzinfo=UTC), edges=[invalid_edge]
        )
