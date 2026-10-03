from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from alpha_workbench.agents.alpha_generator import AlphaGeneratorAgent, AlphaGeneratorService
from alpha_workbench.llm.models import FakeLLMClient
from scripts import verify_paid_wave4 as smoke


def _manifest_and_definitions():
    _, definitions, built = smoke.build_smoke_inputs()
    return built["manifest"], definitions


def test_dry_run_builds_real_pinned_features_without_creating_a_client(monkeypatch) -> None:
    def forbidden_client(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("dry run must not create an LLM client")

    monkeypatch.setattr(smoke, "create_llm", forbidden_client)
    report = smoke.run(execute_paid=False)
    manifest, definitions = _manifest_and_definitions()
    refs = smoke.manifest_feature_refs(manifest, definitions)

    assert report["mode"] == "dry-run"
    assert report["llm_call_count"] == 0
    assert report["llm_call_limit"] == 1
    assert len(refs) == 2
    assert {ref["feature_version_id"] for ref in refs} == {
        "close_return:v1",
        "volume_change:v1",
    }
    assert {ref["dataset_version_id"] for ref in refs} == {
        smoke.DATASET_VERSION
    }
    assert all(ref["available"] for ref in refs)
    assert manifest.feature_observations


def test_manifest_refuses_missing_definition_pin_unavailable_or_future_rows() -> None:
    manifest, definitions = _manifest_and_definitions()
    broken_digest = manifest.model_copy(update={"feature_definition_digests": {}})
    with pytest.raises(ValueError, match="digest is not pinned"):
        smoke.manifest_feature_refs(broken_digest, definitions)

    missing_dataset_pin = manifest.model_copy(update={"dataset_versions": {}})
    with pytest.raises(ValueError, match="missing pins"):
        smoke.manifest_feature_refs(missing_dataset_pin, definitions)

    unavailable = manifest.model_copy(
        update={
            "readiness": tuple(
                item.model_copy(update={"status": "unavailable"})
                if item.feature_name == "close_return"
                else item
                for item in manifest.readiness
            )
        }
    )
    with pytest.raises(ValueError, match="unavailable"):
        smoke.manifest_feature_refs(unavailable, definitions)

    future_row = manifest.feature_observations[0].model_copy(
        update={"available_at": manifest.as_of_time + timedelta(seconds=1)}
    )
    future = manifest.model_copy(
        update={"feature_observations": (future_row, *manifest.feature_observations[1:])}
    )
    with pytest.raises(ValueError, match="future observations"):
        smoke.manifest_feature_refs(future, definitions)


def test_service_output_is_canonical_deduplicated_and_capped(monkeypatch) -> None:
    _, definitions, built = smoke.build_smoke_inputs()
    manifest = built["manifest"]
    client = FakeLLMClient(
        {
            "candidates": [
                {"id": "a", "expression": "Rank(close_return)", "rationale": "rank"},
                {"id": "b", "expression": "Rank(close_return)", "rationale": "duplicate"},
                {"id": "c", "expression": "Rank(volume_change)", "rationale": "volume"},
                {"id": "d", "expression": "Rank(close_return)", "rationale": "extra"},
            ]
        }
    )
    agent = AlphaGeneratorAgent(client, max_candidates=smoke.MAX_CANDIDATES)
    result = AlphaGeneratorService(agent).generate(
        smoke.build_payload(manifest, definitions),
        experiment_id=smoke.EXPERIMENT_ID,
        trial_limit=smoke.TRIAL_LIMIT,
    )

    smoke.validate_result(result, manifest, definitions)
    assert len(result.candidates) == 2
    assert len({candidate.canonical_expression for candidate in result.candidates}) == 2
    assert result.trial_count == 2


def test_paid_switch_makes_one_client_call_and_records_safe_metadata(monkeypatch) -> None:
    class CountingClient:
        def __init__(self) -> None:
            self.calls = 0

        def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
            self.calls += 1
            return {
                "candidates": [
                    {
                        "id": "candidate-1",
                        "expression": "Rank(close_return)",
                        "rationale": "bounded smoke hypothesis",
                    }
                ]
            }

    client = CountingClient()
    monkeypatch.setattr(smoke, "create_llm", lambda _config: client)
    monkeypatch.setattr(smoke.Path, "cwd", lambda: smoke.Path(__file__).resolve().parents[1])

    report = smoke.run(execute_paid=True)

    assert client.calls == 1
    assert report["llm_call_count"] == 1
    assert report["trial_count"] == 1
    assert report["model"]
    assert report["provider"]
    assert "api_key" not in str(report).lower()
    assert "rationale" not in str(report).lower()
