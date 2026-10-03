"""Deterministic offline feature builders with strict cutoff and provenance checks."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, pstdev

from alpha_workbench.temporal_graph import TemporalGraphSnapshot

from .contracts import (
    FeatureDefinition,
    FeatureFamily,
    FeatureFrameManifest,
    FeatureInputFrame,
    FeatureInputObservation,
    FeatureObservation,
    FeatureReadiness,
    FeatureSetVersion,
)


def default_feature_catalog() -> tuple[FeatureDefinition, ...]:
    """Catalog features with working deterministic builders, not placeholder rows."""
    specs: tuple[tuple[str, FeatureFamily, str, str, tuple[str, ...], bool], ...] = (
        (
            "graph_propagation_exposure",
            "graph_propagation",
            "daily",
            "Eligible active edge exposure propagated by coefficient.",
            (),
            True,
        ),
        (
            "neighbor_signal_lag",
            "neighbor_lag",
            "daily",
            "Mean latest prior neighbor signal, weighted by propagation coefficient.",
            ("signal",),
            True,
        ),
        (
            "graph_degree_centrality",
            "centrality_concentration",
            "daily",
            "Eligible active graph degree divided by available node count minus one.",
            (),
            True,
        ),
        (
            "graph_exposure_concentration",
            "centrality_concentration",
            "daily",
            "Herfindahl concentration of eligible outgoing economic exposure.",
            (),
            True,
        ),
        (
            "lead_lag_correlation",
            "statistical_lead_lag",
            "daily",
            "Pearson correlation between current x and prior-period y.",
            ("x", "y"),
            False,
        ),
        (
            "close_return",
            "price_volume",
            "daily",
            "Close-to-close simple return.",
            ("close",),
            False,
        ),
        (
            "volume_change",
            "price_volume",
            "daily",
            "Volume change from the prior observation.",
            ("volume",),
            False,
        ),
        (
            "realized_volatility",
            "volatility",
            "daily",
            "Population standard deviation of trailing close returns.",
            ("close",),
            False,
        ),
        (
            "gross_margin",
            "fundamentals",
            "quarterly",
            "Gross profit divided by revenue.",
            ("revenue", "gross_profit"),
            False,
        ),
        (
            "return_on_assets",
            "fundamentals",
            "quarterly",
            "Net income divided by total assets.",
            ("net_income", "total_assets"),
            False,
        ),
        (
            "earnings_surprise",
            "earnings_events",
            "event",
            "Actual earnings minus consensus, scaled by absolute consensus (floor 1e-9).",
            ("actual", "consensus"),
            False,
        ),
        (
            "event_count_30d",
            "earnings_events",
            "event",
            "Number of source events in the trailing 30 days.",
            (),
            False,
        ),
        (
            "language_sentiment_drift",
            "language_drift",
            "daily",
            "Current sentiment score minus the prior available score.",
            ("sentiment",),
            False,
        ),
        (
            "macro_change",
            "macro_fx",
            "daily",
            "Macro series percentage change from its prior observation.",
            ("macro",),
            False,
        ),
        (
            "fx_return",
            "macro_fx",
            "daily",
            "FX rate simple return from its prior observation.",
            ("fx_rate",),
            False,
        ),
    )
    return tuple(
        FeatureDefinition(
            feature_id=name,
            name=name,
            family=family,
            description=description,
            frequency=frequency,  # type: ignore[arg-type]
            inputs=inputs or ("temporal_graph_v2",),
            required_graph=required_graph,
            output_type="integer" if name == "event_count_30d" else "float",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for name, family, frequency, description, inputs, required_graph in specs
    )


def build_feature_frame(
    feature_set: FeatureSetVersion,
    definitions: tuple[FeatureDefinition, ...],
    *,
    input_frames: dict[FeatureFamily, FeatureInputFrame],
    as_of_time: datetime,
    graph_snapshot: TemporalGraphSnapshot | None = None,
    knowledge_time: datetime | None = None,
    effective_time: datetime | None = None,
) -> FeatureFrameManifest:
    """Build selected features and explicitly report each unavailable feature."""
    if as_of_time.tzinfo is None or as_of_time.utcoffset() is None:
        raise ValueError("as_of_time must include a timezone offset")
    effective_knowledge_time = knowledge_time or as_of_time
    graph_effective_time = effective_time or as_of_time
    if effective_knowledge_time.tzinfo is None or effective_knowledge_time.utcoffset() is None:
        raise ValueError("knowledge_time must include a timezone offset")
    if graph_effective_time.tzinfo is None or graph_effective_time.utcoffset() is None:
        raise ValueError("effective_time must include a timezone offset")
    if graph_effective_time > as_of_time:
        raise ValueError("effective_time cannot be after frame as_of_time")
    definition_map = {f"{item.feature_id}:v{item.version}": item for item in definitions}
    selected: list[FeatureDefinition] = []
    for ref in feature_set.feature_definition_refs:
        try:
            selected.append(definition_map[ref])
        except KeyError as error:
            raise ValueError(f"unknown feature definition reference {ref!r}") from error

    _validate_definitions(selected)
    _validate_inputs(feature_set, input_frames, as_of_time)
    if graph_snapshot is not None:
        if graph_snapshot.published_at > as_of_time:
            raise ValueError("pinned graph snapshot was published after as_of_time")
        if feature_set.graph_snapshot_id != graph_snapshot.snapshot_id:
            raise ValueError("graph snapshot does not match the feature set pin")
        if feature_set.graph_snapshot_digest != graph_snapshot.content_digest:
            raise ValueError("graph snapshot digest does not match the feature set pin")

    values: list[FeatureObservation] = []
    readiness: list[FeatureReadiness] = []
    for definition in selected:
        if definition.required_graph:
            if graph_snapshot is None:
                readiness.append(
                    _unavailable(definition, "no graph snapshot is pinned", as_of_time)
                )
                continue
            graph_frame = None
            if definition.family == "neighbor_lag":
                graph_frame = input_frames.get("neighbor_lag")
                if graph_frame is None:
                    readiness.append(
                        _unavailable(
                            definition, "no neighbor signal frame was supplied", as_of_time
                        )
                    )
                    continue
                expected_version = feature_set.dataset_versions.get("neighbor_lag")
                if expected_version is None:
                    readiness.append(
                        _unavailable(
                            definition,
                            "neighbor signal dataset version is not pinned",
                            as_of_time,
                        )
                    )
                    continue
                if graph_frame.dataset_version != expected_version:
                    raise ValueError(
                        "neighbor signal dataset version does not match the feature set pin"
                    )
                if graph_frame.frequency != definition.frequency:
                    raise ValueError(
                        "neighbor signal frame frequency does not match feature frequency"
                    )
            family_values = _build_graph_feature(
                definition,
                graph_snapshot,
                as_of_time,
                graph_frame,
                effective_knowledge_time,
                graph_effective_time,
            )
            values.extend(family_values)
            readiness.append(_ready_or_empty(definition, family_values, as_of_time))
            continue
        frame = input_frames.get(definition.family)
        if frame is None:
            readiness.append(_unavailable(definition, "no source frame was supplied", as_of_time))
            continue
        expected_version = feature_set.dataset_versions.get(definition.family)
        if expected_version is None:
            readiness.append(
                _unavailable(definition, "source dataset version is not pinned", as_of_time)
            )
            continue
        if frame.dataset_version != expected_version:
            raise ValueError(
                f"{definition.family} dataset version {frame.dataset_version!r} does not "
                "match pinned version"
            )
        if frame.frequency != definition.frequency:
            raise ValueError(
                f"{definition.name} requires {definition.frequency} inputs, got {frame.frequency}"
            )
        family_values = _build_dataset_feature(definition, frame, as_of_time)
        values.extend(family_values)
        readiness.append(_ready_or_empty(definition, family_values, as_of_time))

    manifest_key = "|".join(
        (
            feature_set.feature_set_id,
            str(feature_set.version),
            as_of_time.astimezone(UTC).isoformat(),
            feature_set.graph_snapshot_id or "no-graph",
            feature_set.graph_snapshot_digest or "no-graph-digest",
            effective_knowledge_time.astimezone(UTC).isoformat(),
            graph_effective_time.astimezone(UTC).isoformat(),
            *feature_set.feature_definition_refs,
            *(f"{key}={value}" for key, value in sorted(feature_set.dataset_versions.items())),
        )
    )
    manifest_id = "feature-frame-" + hashlib.sha256(manifest_key.encode()).hexdigest()[:24]
    return FeatureFrameManifest(
        manifest_id=manifest_id,
        feature_set_id=feature_set.feature_set_id,
        feature_set_version=feature_set.version,
        feature_set_digest=feature_set.content_sha256(),
        feature_definition_digests={
            f"{item.feature_id}:v{item.version}": item.content_sha256() for item in selected
        },
        as_of_time=as_of_time,
        effective_time=graph_effective_time,
        knowledge_time=effective_knowledge_time,
        feature_observations=tuple(values),
        readiness=tuple(readiness),
        dataset_versions=dict(feature_set.dataset_versions),
        graph_snapshot_id=feature_set.graph_snapshot_id,
        graph_snapshot_digest=feature_set.graph_snapshot_digest,
        created_at=as_of_time,
    )


def _validate_inputs(
    feature_set: FeatureSetVersion,
    frames: dict[FeatureFamily, FeatureInputFrame],
    as_of_time: datetime,
) -> None:
    for family, frame in frames.items():
        if family != frame.family:
            raise ValueError("source frame key does not match its family")
        if frame.dataset_version != feature_set.dataset_versions.get(family):
            raise ValueError(f"{family} input dataset version is not pinned by the feature set")
        for observation in frame.observations:
            if observation.observed_at > as_of_time or observation.available_at > as_of_time:
                raise ValueError(f"{family} input contains an observation after as_of_time")


def _validate_definitions(definitions: list[FeatureDefinition]) -> None:
    """Prevent stored schemas from claiming inputs or units the builder ignores."""
    catalog = {item.name: item for item in default_feature_catalog()}
    for definition in definitions:
        expected = catalog.get(definition.name)
        if expected is None:
            raise ValueError(f"no deterministic builder is registered for {definition.name!r}")
        fields = ("family", "frequency", "inputs", "output_type", "required_graph")
        if any(getattr(definition, field) != getattr(expected, field) for field in fields):
            raise ValueError(f"{definition.name} definition schema does not match its builder")


def _build_dataset_feature(
    definition: FeatureDefinition, frame: FeatureInputFrame, as_of_time: datetime
) -> list[FeatureObservation]:
    records: dict[str, list[FeatureInputObservation]] = defaultdict(list)
    for observation in sorted(
        frame.observations, key=lambda item: (item.entity_id, item.observed_at)
    ):
        records[observation.entity_id].append(observation)
    output: list[FeatureObservation] = []
    for entity_id, rows in records.items():
        pairs: list[tuple[FeatureInputObservation, float | int | None]] = []
        if definition.name == "close_return":
            for prior, current in zip(rows, rows[1:], strict=False):
                old, new = _number(prior.values.get("close")), _number(current.values.get("close"))
                if old is not None and new is not None and old != 0:
                    pairs.append((current, (new / old) - 1.0))
        elif definition.name == "volume_change":
            for prior, current in zip(rows, rows[1:], strict=False):
                old, new = (
                    _number(prior.values.get("volume")),
                    _number(current.values.get("volume")),
                )
                if old is not None and new is not None and old != 0:
                    pairs.append((current, (new / old) - 1.0))
        elif definition.name == "realized_volatility":
            closes = [_number(row.values.get("close")) for row in rows]
            returns: list[float] = []
            for old, new in zip(closes, closes[1:], strict=False):
                if old is not None and new is not None and old != 0:
                    returns.append(new / old - 1.0)
            if returns:
                pairs.append((rows[-1], pstdev(returns[-20:])))
        elif definition.name == "gross_margin":
            for row in rows:
                revenue, gross = (
                    _number(row.values.get("revenue")),
                    _number(row.values.get("gross_profit")),
                )
                if revenue:
                    pairs.append((row, gross / revenue if gross is not None else None))
        elif definition.name == "return_on_assets":
            for row in rows:
                income, assets = (
                    _number(row.values.get("net_income")),
                    _number(row.values.get("total_assets")),
                )
                if assets:
                    pairs.append((row, income / assets if income is not None else None))
        elif definition.name == "earnings_surprise":
            for row in rows:
                actual, consensus = (
                    _number(row.values.get("actual")),
                    _number(row.values.get("consensus")),
                )
                if actual is not None and consensus is not None:
                    pairs.append((row, (actual - consensus) / max(abs(consensus), 1e-9)))
        elif definition.name == "event_count_30d":
            for row in rows:
                count = sum(
                    int((row.observed_at - prior.observed_at).total_seconds() <= 30 * 86400)
                    for prior in rows
                    if prior.observed_at <= row.observed_at
                )
                pairs.append((row, count))
        elif definition.name == "language_sentiment_drift":
            for prior, current in zip(rows, rows[1:], strict=False):
                old, new = (
                    _number(prior.values.get("sentiment")),
                    _number(current.values.get("sentiment")),
                )
                if old is not None and new is not None:
                    pairs.append((current, new - old))
        elif definition.name in {"macro_change", "fx_return"}:
            key = "macro" if definition.name == "macro_change" else "fx_rate"
            for prior, current in zip(rows, rows[1:], strict=False):
                old, new = _number(prior.values.get(key)), _number(current.values.get(key))
                if old is not None and new is not None and old != 0:
                    pairs.append((current, new / old - 1.0))
        elif definition.name == "lead_lag_correlation":
            series = [(_number(row.values.get("x")), _number(row.values.get("y"))) for row in rows]
            aligned: list[tuple[float | None, float | None]] = [
                (series[index][0], series[index - 1][1]) for index in range(1, len(series))
            ]
            valid_aligned: list[tuple[float, float]] = []
            for x_value, y_value in aligned:
                if x_value is not None and y_value is not None:
                    valid_aligned.append((x_value, y_value))
            if len(valid_aligned) >= 2:
                pairs.append(
                    (
                        rows[-1],
                        _correlation(
                            [x for x, _ in valid_aligned],
                            [y for _, y in valid_aligned],
                        ),
                    )
                )
        for source, value in pairs:
            if value is None:
                continue
            if definition.output_type == "integer" and not isinstance(value, int):
                raise ValueError(f"{definition.name} builder output does not match integer schema")
            output.append(
                FeatureObservation(
                    feature_id=definition.feature_id,
                    feature_name=definition.name,
                    entity_id=entity_id,
                    observed_at=source.observed_at,
                    available_at=source.available_at,
                    value=value if definition.output_type == "integer" else float(value),
                    dataset_version=frame.dataset_version,
                    created_at=source.available_at,
                )
            )
    return [
        item
        for item in output
        if item.observed_at <= as_of_time and item.available_at <= as_of_time
    ]


def _build_graph_feature(
    definition: FeatureDefinition,
    snapshot: TemporalGraphSnapshot,
    as_of_time: datetime,
    signal_frame: FeatureInputFrame | None = None,
    knowledge_time: datetime | None = None,
    effective_time: datetime | None = None,
) -> list[FeatureObservation]:
    graph_effective_time = effective_time or as_of_time
    edges = tuple(
        edge
        for edge in snapshot.visible_edge_states(
            as_of_time=graph_effective_time, knowledge_time=knowledge_time or as_of_time
        )
        if edge.lifecycle_status == "active" and edge.strategy_eligible == "eligible"
    )
    nodes = {node.node_id for node in snapshot.nodes if node.kind in {"entity", "instrument"}}
    scores: dict[str, float] = defaultdict(float)
    if definition.name == "graph_propagation_exposure":
        for edge in edges:
            scores[edge.target_node_id] += edge.economic_exposure * edge.propagation_coefficient
    elif definition.name == "graph_degree_centrality":
        denominator = max(1, len(nodes) - 1)
        for edge in edges:
            scores[edge.source_node_id] += 1.0 / denominator
            scores[edge.target_node_id] += 1.0 / denominator
    elif definition.name == "graph_exposure_concentration":
        exposures: dict[str, list[float]] = defaultdict(list)
        for edge in edges:
            exposures[edge.source_node_id].append(edge.economic_exposure)
        for node in nodes:
            weights = exposures.get(node, [])
            total = sum(weights)
            scores[node] = sum((weight / total) ** 2 for weight in weights) if total else 0.0
    elif definition.name == "neighbor_signal_lag":
        if signal_frame is None:
            return []
        latest_signal: dict[str, FeatureInputObservation] = {}
        for item in signal_frame.observations:
            if item.observed_at < graph_effective_time and item.available_at <= as_of_time:
                old = latest_signal.get(item.entity_id)
                if old is None or item.observed_at > old.observed_at:
                    latest_signal[item.entity_id] = item
        weighted: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for edge in edges:
            row = latest_signal.get(edge.source_node_id)
            if row is not None:
                signal = _number(row.values.get("signal"))
                if signal is not None:
                    weighted[edge.target_node_id].append((signal, edge.propagation_coefficient))
        for node, items in weighted.items():
            weighted_denominator = 0.0
            weighted_numerator = 0.0
            for signal_value, edge_weight in items:
                weighted_denominator += edge_weight
                weighted_numerator += signal_value * edge_weight
            if weighted_denominator > 0:
                scores[node] = weighted_numerator / weighted_denominator
    output_nodes = sorted(scores) if definition.name == "neighbor_signal_lag" else sorted(nodes)
    return [
        FeatureObservation(
            feature_id=definition.feature_id,
            feature_name=definition.name,
            entity_id=node,
            observed_at=graph_effective_time,
            available_at=max(as_of_time, snapshot.published_at),
            value=scores.get(node, 0.0),
            graph_snapshot_id=snapshot.snapshot_id,
            graph_snapshot_digest=snapshot.content_digest,
            dataset_version=(signal_frame.dataset_version if signal_frame is not None else None),
            created_at=as_of_time,
        )
        for node in output_nodes
    ]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean, right_mean = mean(left), mean(right)
    left_sd, right_sd = pstdev(left), pstdev(right)
    if left_sd == 0 or right_sd == 0:
        return None
    return sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)) / (
        len(left) * left_sd * right_sd
    )


def _unavailable(
    definition: FeatureDefinition, reason: str, created_at: datetime
) -> FeatureReadiness:
    return FeatureReadiness(
        feature_id=definition.feature_id,
        feature_name=definition.name,
        status="unavailable",
        reason=reason,
        created_at=created_at,
    )


def _ready_or_empty(
    definition: FeatureDefinition, observations: list[FeatureObservation], created_at: datetime
) -> FeatureReadiness:
    return FeatureReadiness(
        feature_id=definition.feature_id,
        feature_name=definition.name,
        status="ready" if observations else "unavailable",
        reason="computed from pinned point-in-time inputs"
        if observations
        else "inputs did not contain enough valid values",
        observation_count=len(observations),
        created_at=created_at,
    )
