"""Explicitly gated, one-call Wave 4 alpha-generator smoke harness.

The default mode is offline and key-free. Add ``--execute-paid`` only for an
intentional call through the configured ``alpha_generator`` role. The model
receives refs derived from a deterministic, point-in-time feature manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alpha_workbench.agents.alpha_generator import AlphaGeneratorAgent, AlphaGeneratorService
from alpha_workbench.alpha import GeneratorFeatureRef
from alpha_workbench.alpha.dsl import canonicalize_expression, parse_expression
from alpha_workbench.evidence import DuckDBEvidenceLedger, MarketBar
from alpha_workbench.features import (
    FeatureInputFrame,
    FeatureInputObservation,
    FeatureSetVersion,
    build_feature_frame,
    default_feature_catalog,
)
from alpha_workbench.llm.models import create_llm, load_model_config

MAX_LLM_CALLS = 1
MAX_CANDIDATES = 3
TRIAL_LIMIT = 3
EXPERIMENT_ID = "paid-wave4-smoke"
AS_OF_TIME = datetime(2026, 10, 2, 21, tzinfo=UTC)
DATASET_VERSION = "wave4-smoke-price-volume-v1"
SELECTED_FEATURES = ("close_return", "volume_change")


def build_smoke_inputs() -> tuple[FeatureSetVersion, tuple[Any, ...], dict[str, Any]]:
    """Build fixed input rows and the manifest-backed feature catalog."""
    catalog = tuple(
        item for item in default_feature_catalog() if item.name in SELECTED_FEATURES
    )
    if {item.name for item in catalog} != set(SELECTED_FEATURES):
        raise RuntimeError("smoke feature definitions are missing from the deterministic catalog")

    feature_set = FeatureSetVersion(
        feature_set_id="wave4-smoke-price-volume",
        version=1,
        feature_definition_refs=tuple(f"{item.feature_id}:v{item.version}" for item in catalog),
        dataset_versions={"price_volume": DATASET_VERSION},
    )
    previous = AS_OF_TIME - timedelta(days=1)
    frame = FeatureInputFrame(
        family="price_volume",
        frequency="daily",
        dataset_version=DATASET_VERSION,
        observations=(
            FeatureInputObservation(
                entity_id="SMOKE:ABC",
                observed_at=previous,
                available_at=previous,
                values={"close": 100.0, "volume": 1000.0},
            ),
            FeatureInputObservation(
                entity_id="SMOKE:ABC",
                observed_at=AS_OF_TIME - timedelta(hours=1),
                available_at=AS_OF_TIME - timedelta(minutes=30),
                values={"close": 102.0, "volume": 1200.0},
            ),
        ),
    )
    manifest = build_feature_frame(
        feature_set,
        catalog,
        input_frames={"price_volume": frame},
        as_of_time=AS_OF_TIME,
    )
    return feature_set, catalog, {"price_volume": frame, "manifest": manifest}


def build_local_market_inputs(
    root: Path,
) -> tuple[FeatureSetVersion, tuple[Any, ...], dict[str, Any]]:
    """Build the paid smoke manifest from locally collected market observations.

    The ignored evidence ledger contains prior adapter output. Requiring it for
    paid mode prevents a successful cloud smoke from being mistaken for a test
    over fabricated prices.
    """
    ledger_path = root / "data" / "private" / "evidence.duckdb"
    if not ledger_path.exists():
        raise RuntimeError("paid smoke requires the ignored local evidence ledger")
    with DuckDBEvidenceLedger(ledger_path) as ledger:
        market = [
            item
            for item in ledger.observations_as_of(datetime.now(UTC))
            if isinstance(item.payload, MarketBar)
        ]
    by_symbol: dict[str, list[Any]] = {}
    for item in market:
        by_symbol.setdefault(item.payload.symbol, []).append(item)
    selected = []
    for _symbol, rows in sorted(by_symbol.items()):
        ordered = sorted(rows, key=lambda item: item.payload.bar_end)
        if len(ordered) >= 2:
            selected.extend(ordered[-30:])
    if len({item.payload.symbol for item in selected}) < 2:
        raise RuntimeError("paid smoke requires at least two symbols with two market bars each")

    digest_input = "|".join(sorted(item.idempotency_key for item in selected))
    dataset_version = "local-market-" + hashlib.sha256(digest_input.encode()).hexdigest()[:16]
    as_of_time = max(
        max(item.payload.bar_end, item.document.available_at) for item in selected
    )
    definitions = tuple(
        item for item in default_feature_catalog() if item.name in SELECTED_FEATURES
    )
    feature_set = FeatureSetVersion(
        feature_set_id="wave4-paid-local-market",
        version=1,
        feature_definition_refs=tuple(
            f"{item.feature_id}:v{item.version}" for item in definitions
        ),
        dataset_versions={"price_volume": dataset_version},
    )
    frame = FeatureInputFrame(
        family="price_volume",
        frequency="daily",
        dataset_version=dataset_version,
        observations=tuple(
            FeatureInputObservation(
                entity_id=item.payload.symbol,
                observed_at=item.payload.bar_end,
                available_at=item.document.available_at,
                values={"close": item.payload.close, "volume": item.payload.volume},
            )
            for item in selected
        ),
    )
    manifest = build_feature_frame(
        feature_set,
        definitions,
        input_frames={"price_volume": frame},
        as_of_time=as_of_time,
    )
    return feature_set, definitions, {
        "price_volume": frame,
        "manifest": manifest,
        "symbols": tuple(sorted({item.payload.symbol for item in selected})),
    }


def manifest_feature_refs(manifest: Any, definitions: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Return only ready, observed features with complete immutable source pins."""
    readiness = {item.feature_id: item for item in manifest.readiness}
    definition_by_id = {item.feature_id: item for item in definitions}
    refs: list[dict[str, Any]] = []
    for feature_id, definition in definition_by_id.items():
        state = readiness.get(feature_id)
        if state is None or state.status != "ready" or state.observation_count < 1:
            raise ValueError(f"feature {definition.name!r} is unavailable in the smoke manifest")
        definition_pin = f"{feature_id}:v{definition.version}"
        if manifest.feature_definition_digests.get(definition_pin) != definition.content_sha256():
            raise ValueError(f"feature {definition.name!r} definition digest is not pinned")
        rows = [item for item in manifest.feature_observations if item.feature_id == feature_id]
        if len(rows) != state.observation_count:
            raise ValueError(f"feature {definition.name!r} readiness count does not match rows")
        if any(
            item.dataset_version != manifest.dataset_versions.get(definition.family)
            or item.dataset_version is None
            or item.observed_at > manifest.as_of_time
            or item.available_at > manifest.as_of_time
            for item in rows
        ):
            raise ValueError(f"feature {definition.name!r} has missing pins or future observations")
        if not rows:
            raise ValueError(f"feature {definition.name!r} has no observations")
        refs.append(
            GeneratorFeatureRef(
                name=definition.name,
                description=definition.description,
                frequency=definition.frequency,
                feature_version_id=definition_pin,
                dataset_version_id=manifest.dataset_versions[definition.family],
                available_at=max(item.available_at for item in rows),
                available=True,
            ).model_dump(mode="json")
        )
    if len(refs) != len(definitions):
        raise ValueError("smoke feature catalog did not fully resolve from the manifest")
    return refs


def build_payload(manifest: Any, definitions: tuple[Any, ...]) -> dict[str, object]:
    return {
        "features": manifest_feature_refs(manifest, definitions),
        "as_of_time": manifest.as_of_time.isoformat(),
        "frequency": "daily",
        "feature_frequency_policy": "strict",
        "max_candidates": MAX_CANDIDATES,
        "context": "Propose a research hypothesis from the pinned daily feature catalog.",
    }


def validate_result(result: Any, manifest: Any, definitions: tuple[Any, ...]) -> None:
    if len(result.candidates) > MAX_CANDIDATES:
        raise ValueError("alpha generator exceeded the three-candidate smoke limit")
    source_refs = {ref["name"]: ref for ref in manifest_feature_refs(manifest, definitions)}
    canonical_seen: set[str] = set()
    for candidate in result.candidates:
        signal = candidate.signal
        if signal is None:
            raise ValueError(f"candidate {candidate.id!r} has no validated signal")
        canonical = canonicalize_expression(candidate.expression, set(source_refs))
        parse_expression(canonical, set(source_refs))
        if canonical != candidate.expression or canonical in canonical_seen:
            raise ValueError("candidate formulas must be canonical and unique")
        canonical_seen.add(canonical)
        for reference in signal.feature_refs:
            expected = source_refs.get(reference.name)
            if expected is None:
                raise ValueError(f"candidate {candidate.id!r} references an unknown feature")
            if (
                reference.feature_version_id != expected["feature_version_id"]
                or reference.dataset_version_id != expected["dataset_version_id"]
            ):
                raise ValueError(f"candidate {candidate.id!r} lost a feature source pin")


def _metadata(
    result: Any,
    *,
    provider: str,
    model: str,
    call_count: int,
    manifest: Any,
    input_mode: str,
    symbols: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "mode": "paid" if call_count else "dry-run",
        "provider": provider,
        "model": model,
        "llm_call_count": call_count,
        "llm_call_limit": MAX_LLM_CALLS,
        "candidate_limit": MAX_CANDIDATES,
        "trial_limit": TRIAL_LIMIT,
        "experiment_id": EXPERIMENT_ID,
        "trial_count": result.trial_count if result else 0,
        "feature_manifest_id": manifest.manifest_id,
        "feature_manifest_digest": manifest.content_sha256(),
        "feature_as_of_time": manifest.as_of_time.isoformat(),
        "input_mode": input_mode,
        "symbols": list(symbols),
        "candidates": [
            {"id": item.id, "canonical_formula": item.canonical_expression}
            for item in (result.candidates if result else [])
        ],
        "rejected_count": len(result.rejected) if result else 0,
    }


def run(*, execute_paid: bool) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    if execute_paid:
        _, definitions, built = build_local_market_inputs(root)
    else:
        _, definitions, built = build_smoke_inputs()
    manifest = built["manifest"]
    payload = build_payload(manifest, definitions)
    role = load_model_config(root / "config" / "models.yaml", "alpha_generator")

    if not execute_paid:
        return _metadata(
            None,
            provider=role.provider,
            model=role.model,
            call_count=0,
            manifest=manifest,
            input_mode="deterministic-dry-run",
        )
    if role.provider == "fake":
        raise RuntimeError("paid execution requires a non-fake alpha_generator provider")
    if Path.cwd().resolve() != root.resolve():
        raise RuntimeError(
            "run paid smoke from the repository root so the existing budget ledger applies"
        )

    llm = create_llm(role)
    agent = AlphaGeneratorAgent(llm, max_candidates=MAX_CANDIDATES)
    service = AlphaGeneratorService(agent)
    result = service.generate(
        payload,
        run_id="paid-wave4-smoke",
        experiment_id=EXPERIMENT_ID,
        trial_limit=TRIAL_LIMIT,
    )
    validate_result(result, manifest, definitions)
    return _metadata(
        result,
        provider=role.provider,
        model=role.model,
        call_count=1,
        manifest=manifest,
        input_mode="local-evidence-ledger-market-bars",
        symbols=built["symbols"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "build and validate the local manifest without keys, network calls, or spending "
            "(default)"
        ),
    )
    modes.add_argument(
        "--execute-paid",
        action="store_true",
        help="make one explicitly authorized call through the configured alpha_generator role",
    )
    args = parser.parse_args()
    print(json.dumps(run(execute_paid=args.execute_paid), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
