"""Pure service functions for temporal graph bootstrap and maintenance."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import TypeAlias

from alpha_workbench.evidence import EvidenceObservation, TextEvidence
from alpha_workbench.extraction import EdgeProposal, EvidenceValidationReport
from alpha_workbench.product import InstrumentRef
from alpha_workbench.temporal_graph.contracts import (
    EligibilityStatus,
    GraphEdgeState,
    GraphNode,
    GraphRelationship,
    TemporalGraphSnapshot,
)
from alpha_workbench.temporal_graph.repository import TemporalGraphRepository

from .contracts import (
    EdgeEligibility,
    EvidenceAssessment,
    GraphPipelineReport,
    GraphPipelineRequest,
)
from .policy import (
    EVIDENCE_HALF_LIFE_DAYS,
    RETIRE_AFTER_HALF_LIVES,
    assess_edge,
    evidence_quality,
)

_RELATION_NAMES = {
    "manufacturing_dependency": "Manufacturing dependency",
    "equipment_dependency": "Equipment dependency",
    "packaging_dependency": "Packaging dependency",
    "customer_concentration": "Customer concentration",
    "competitive_substitution": "Competitive substitution",
    "ip_or_license": "IP or license",
    "geographic_or_regulatory": "Geographic or regulatory exposure",
}

EdgeKey: TypeAlias = tuple[str, str, str]
ProposalObservation: TypeAlias = tuple[EdgeProposal, EvidenceObservation]


def bootstrap_graph(
    request: GraphPipelineRequest, repository: TemporalGraphRepository
) -> tuple[TemporalGraphSnapshot, GraphPipelineReport]:
    """Build the first full graph for a locked universe and publish without HITL."""
    if request.trigger != "bootstrap":
        raise ValueError("bootstrap_graph requires trigger='bootstrap'")
    prior = _latest_or_none(repository, request.universe.workspace_id)
    if prior is not None:
        request_key = _request_key(request)
        for stored in repository.list(request.universe.workspace_id):
            if stored.source_run_id == request_key:
                return stored, GraphPipelineReport(
                    snapshot_id=stored.snapshot_id,
                    published=False,
                    idempotent_replay=True,
                    trigger="bootstrap",
                )
        return update_graph(request.model_copy(update={"trigger": "nightly"}), repository)
    return _run(request, repository, None)


def update_graph(
    request: GraphPipelineRequest, repository: TemporalGraphRepository
) -> tuple[TemporalGraphSnapshot, GraphPipelineReport]:
    """Create a full immutable snapshot while changing only affected edge states."""
    if request.trigger == "bootstrap":
        raise ValueError("update_graph requires trigger='nightly' or 'event'")
    prior = _latest_or_none(repository, request.universe.workspace_id)
    return _run(request, repository, prior)


def _run(
    request: GraphPipelineRequest,
    repository: TemporalGraphRepository,
    prior: TemporalGraphSnapshot | None,
) -> tuple[TemporalGraphSnapshot, GraphPipelineReport]:
    if request.knowledge_time < request.as_of_time:
        raise ValueError("knowledge_time cannot precede as_of_time")
    universe = request.universe
    if prior is not None and prior.workspace_id != universe.workspace_id:
        raise ValueError("repository returned a snapshot for another workspace")
    if (
        prior is not None
        and getattr(prior, "universe_id", universe.universe_id) != universe.universe_id
    ):
        raise ValueError("cannot update a graph with a different locked universe")
    if prior is not None and request.knowledge_time < prior.knowledge_time:
        raise ValueError("knowledge_time cannot move behind the latest published snapshot")
    request_key = _request_key(request)
    for stored in repository.list(universe.workspace_id):
        if stored.source_run_id == request_key:
            return stored, GraphPipelineReport(
                snapshot_id=stored.snapshot_id,
                published=False,
                idempotent_replay=True,
                trigger=request.trigger,
            )

    eligible_observations, excluded = _eligible_observations(
        request.observations, request.as_of_time, request.knowledge_time
    )
    nodes, alias_map = _universe_nodes(universe.instruments, request.knowledge_time)
    context_nodes: dict[str, GraphNode] = {}
    for observation in eligible_observations:
        for raw_id in observation.mentioned_entity_ids:
            if raw_id.casefold() in alias_map:
                continue
            context_id = raw_id if raw_id.startswith("external:") else f"external:{raw_id}"
            alias_map[raw_id.casefold()] = context_id
            alias_map[context_id.casefold()] = context_id
            context_nodes.setdefault(
                context_id,
                GraphNode(
                    node_id=context_id,
                    kind="external_context",
                    label=raw_id,
                    created_at=request.knowledge_time,
                    properties={"source": "evidence_mention"},
                    lifecycle_status="active",
                    strategy_eligible=False,
                ),
            )
    entity_ids = set(alias_map.values())
    for alias, target in request.aliases.items():
        canonical_target = _canonical_alias_target(target, alias_map)
        if canonical_target in entity_ids:
            alias_map[alias.casefold()] = canonical_target
    if prior is not None:
        prior_nodes = {node.node_id: node for node in prior.nodes}
        prior_instruments = {node.node_id for node in prior.nodes if node.kind == "instrument"}
        current_instruments = {node.node_id for node in nodes if node.kind == "instrument"}
        if prior_instruments != current_instruments:
            raise ValueError("locked universe node set changed; create a new graph bootstrap")
        # Preserve any future non-universe context nodes owned by the graph contract.
        nodes = list(prior.nodes) + [
            node for node_id, node in context_nodes.items() if node_id not in prior_nodes
        ]
    else:
        nodes.extend(context_nodes.values())
    validation_by_proposal = {
        str(report.proposal_id): report for report in request.validation_reports
    }
    observation_by_id = {str(item.observation_id): item for item in eligible_observations}
    proposal_items = _validated_proposals(
        request, validation_by_proposal, observation_by_id, universe.instruments, alias_map
    )
    assessments = _resolve_assessments(
        request.assessments, observation_by_id, alias_map, entity_ids
    )
    for key, (_proposal, observation) in proposal_items.items():
        if not any(
            a.observation_id == str(observation.observation_id) and _assessment_key(a) == key
            for a in assessments
        ):
            assessments.append(
                EvidenceAssessment(
                    observation_id=str(observation.observation_id),
                    source_entity_id=key[0],
                    target_entity_id=key[1],
                    relationship_type=key[2],
                    stance="support",
                )
            )

    relation_types = sorted(
        {key[2] for key in proposal_items} | {a.relationship_type for a in assessments}
    )
    relationships = _relationship_models(relation_types, prior, request.knowledge_time)
    relationship_ids = {rel.name: rel.relationship_id for rel in relationships}
    grouped: dict[EdgeKey, list[EvidenceObservation]] = defaultdict(list)
    assessments_by_key: dict[EdgeKey, list[EvidenceAssessment]] = defaultdict(list)
    for key, (_, observation) in proposal_items.items():
        grouped[key].append(observation)
    for assessment in assessments:
        key = _assessment_key(assessment)
        grouped[key].append(observation_by_id[assessment.observation_id])
        assessments_by_key[key].append(assessment)

    prior_states = list(prior.edge_states) if prior is not None else []
    active_states = _active_states(prior_states, request.as_of_time, request.knowledge_time)
    affected: set[EdgeKey] = set(grouped)
    if request.trigger == "nightly":
        affected.update(
            (
                s.source_node_id,
                s.target_node_id,
                _relation_name(s.relationship_id, relationships, prior),
            )
            for s in active_states
        )
    decisions: list[EdgeEligibility] = []
    states = list(prior_states)
    changed_edge_ids: list[str] = []
    for key in sorted(affected):
        source_id, target_id, relation_name = key
        relation_id = relationship_ids.get(relation_name) or _relationship_id(relation_name)
        previous = _find_active(active_states, source_id, target_id, relation_id)
        observations = _dedupe_observations(grouped.get(key, []))
        edge_assessments = assessments_by_key.get(key, [])
        if request.trigger == "nightly" and not observations:
            if previous is None:
                continue
            elapsed = max(
                0.0, (request.as_of_time - previous.effective_from).total_seconds() / 86_400
            )
            decay = 2 ** (-elapsed / EVIDENCE_HALF_LIFE_DAYS)
            confidence = round(previous.confidence * decay, 6)
            last_supported_at = previous.attributes.get("last_supported_at")
            stale_from = (
                datetime.fromisoformat(last_supported_at)
                if isinstance(last_supported_at, str)
                else previous.effective_from
            )
            stale_days = max(0.0, (request.as_of_time - stale_from).total_seconds() / 86_400)
            expired = stale_days >= EVIDENCE_HALF_LIFE_DAYS * RETIRE_AFTER_HALF_LIVES
            status = "ineligible" if expired or confidence < 0.20 else previous.strategy_eligible
            reason = (
                "relationship retired after prolonged evidence decay"
                if expired
                else "relationship weakened by deterministic evidence decay"
            )
            decision = EdgeEligibility(
                source_node_id=source_id,
                target_node_id=target_id,
                relationship_id=relation_id,
                status=status,
                confidence=confidence,
                independent_sources=0,
                support_count=0,
                contradiction_count=0,
                reason=reason,
            )
            decisions.append(decision)
            updated = _replace_state(previous, decision, request, expired=expired, decay=decay)
            if updated != previous:
                states, inserted = _close_and_append(
                    states, previous, updated, request.knowledge_time, request.as_of_time
                )
                changed_edge_ids.extend(inserted)
            continue
        if not observations:
            continue
        decision = assess_edge(
            source_node_id=source_id,
            target_node_id=target_id,
            relationship_id=relation_id,
            observations=observations,
            assessments=edge_assessments,
            at=request.as_of_time,
        )
        decisions.append(decision)
        retire = (
            any(a.stance == "retire" for a in edge_assessments) and decision.status == "ineligible"
        )
        if previous is None:
            if retire:
                continue
            state = _new_state(key, decision, observations, request, retire=False)
            states.append(state)
            changed_edge_ids.append(state.edge_id)
        else:
            state = _replace_state(
                previous, decision, request, expired=retire, observations=observations
            )
            if state != previous:
                states, inserted = _close_and_append(
                    states, previous, state, request.knowledge_time, request.as_of_time
                )
                changed_edge_ids.extend(inserted)

    # A replay of the exact request is a no-op, including its immutable snapshot id.
    snapshot = _make_snapshot(request, prior, nodes, relationships, states, request_key)
    if prior is not None and prior.content_digest == snapshot.content_digest:
        return prior, GraphPipelineReport(
            snapshot_id=prior.snapshot_id,
            published=False,
            idempotent_replay=True,
            trigger=request.trigger,
            decisions=tuple(decisions),
            excluded_observation_ids=tuple(excluded),
        )
    existing = {item.snapshot_id for item in repository.list(universe.workspace_id)}
    if snapshot.snapshot_id in existing:
        replay = repository.get(snapshot.snapshot_id)
        if replay.content_digest != snapshot.content_digest:
            raise ValueError("request_id was already used for different graph content")
        return replay, GraphPipelineReport(
            snapshot_id=replay.snapshot_id,
            published=False,
            idempotent_replay=True,
            trigger=request.trigger,
            decisions=tuple(decisions),
            excluded_observation_ids=tuple(excluded),
        )
    repository.publish(snapshot)
    report = GraphPipelineReport(
        snapshot_id=snapshot.snapshot_id,
        published=True,
        trigger=request.trigger,
        affected_edge_ids=tuple(sorted(changed_edge_ids)),
        decisions=tuple(decisions),
        excluded_observation_ids=tuple(excluded),
    )
    return snapshot, report


def _latest_or_none(
    repository: TemporalGraphRepository, workspace_id: str
) -> TemporalGraphSnapshot | None:
    try:
        return repository.latest(workspace_id)
    except KeyError:
        return None


def _request_key(request: GraphPipelineRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _universe_nodes(
    instruments: tuple[InstrumentRef, ...], created_at: datetime
) -> tuple[list[GraphNode], dict[str, str]]:
    entities: dict[str, list[InstrumentRef]] = defaultdict(list)
    aliases: dict[str, str] = {}
    for item in instruments:
        raw_entity_id = item.entity_id or item.instrument_id
        entity_id = _stable_entity_node_id(raw_entity_id)
        entities[entity_id].append(item)
        for alias in (
            raw_entity_id,
            entity_id,
            item.instrument_id,
            item.symbol,
            *item.provider_symbols.values(),
        ):
            aliases[alias.casefold()] = entity_id
    nodes: list[GraphNode] = []
    for entity_id, refs in sorted(entities.items()):
        nodes.append(
            GraphNode(
                node_id=entity_id,
                kind="entity",
                label=entity_id,
                created_at=created_at,
                properties={"instrument_ids": ",".join(sorted(i.instrument_id for i in refs))},
                strategy_eligible=True,
            )
        )
    for item in instruments:
        nodes.append(
            GraphNode(
                node_id=item.instrument_id,
                kind="instrument",
                label=item.symbol,
                created_at=created_at,
                properties={
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "currency": item.currency,
                    "entity_id": _stable_entity_node_id(item.entity_id or item.instrument_id),
                    "figi": item.figi,
                },
                strategy_eligible=True,
            )
        )
    return nodes, aliases


def _stable_entity_node_id(entity_id: str) -> str:
    """Prefix economic IDs so they never collide with instrument node IDs."""
    return entity_id if entity_id.startswith("entity:") else f"entity:{entity_id}"


def _eligible_observations(
    observations: tuple[EvidenceObservation, ...], as_of: datetime, knowledge_time: datetime
) -> tuple[list[EvidenceObservation], list[str]]:
    eligible, excluded = [], []
    for observation in observations:
        if (
            observation.document.available_at <= as_of
            and observation.document.retrieved_at <= knowledge_time
        ):
            eligible.append(observation)
        else:
            excluded.append(str(observation.observation_id))
    return eligible, sorted(excluded)


def _validated_proposals(
    request: GraphPipelineRequest,
    validation_by_proposal: dict[str, EvidenceValidationReport],
    observations: dict[str, EvidenceObservation],
    instruments: tuple[InstrumentRef, ...],
    aliases: dict[str, str],
) -> dict[EdgeKey, ProposalObservation]:
    result: dict[EdgeKey, ProposalObservation] = {}
    universe_ids = set(aliases.values()) | {item.instrument_id for item in instruments}
    known_hashes = {item.document.content_sha256: item for item in observations.values()}
    for proposal in request.validated_proposals:
        validation = validation_by_proposal.get(str(proposal.id))
        if validation is None or validation.verdict != "pass":
            continue
        observation = known_hashes.get(proposal.passage.snapshot_sha256)
        if observation is None:
            continue
        source = _resolve_id(proposal.source_entity_id, aliases)
        target = _resolve_id(proposal.target_entity_id, aliases)
        if source == target or source not in universe_ids or target not in universe_ids:
            continue
        if proposal.evidence_quote.casefold() not in proposal.passage.text.casefold():
            continue
        if (
            isinstance(observation.payload, TextEvidence)
            and proposal.evidence_quote.casefold() not in observation.payload.text.casefold()
        ):
            continue
        key = (source, target, proposal.relationship_type)
        result[key] = (proposal, observation)
    return result


def _resolve_assessments(
    assessments: tuple[EvidenceAssessment, ...],
    observations: dict[str, EvidenceObservation],
    aliases: dict[str, str],
    known_entity_ids: set[str],
) -> list[EvidenceAssessment]:
    output: list[EvidenceAssessment] = []
    for item in assessments:
        if item.observation_id not in observations:
            continue
        source, target = (
            _resolve_id(item.source_entity_id, aliases),
            _resolve_id(item.target_entity_id, aliases),
        )
        if (
            source == target
            or source not in known_entity_ids
            or target not in known_entity_ids
            or item.relationship_type not in _RELATION_NAMES
        ):
            continue
        output.append(
            item.model_copy(update={"source_entity_id": source, "target_entity_id": target})
        )
    return output


def _resolve_id(value: str, aliases: dict[str, str]) -> str:
    return aliases.get(value.casefold(), value)


def _canonical_alias_target(value: str, aliases: dict[str, str]) -> str:
    return aliases.get(value.casefold(), value)


def _assessment_key(item: EvidenceAssessment) -> tuple[str, str, str]:
    return item.source_entity_id, item.target_entity_id, item.relationship_type


def _relationship_id(name: str) -> str:
    return "relationship-" + hashlib.sha256(name.encode()).hexdigest()[:16]


def _relationship_models(
    names: list[str], prior: TemporalGraphSnapshot | None, created_at: datetime
) -> list[GraphRelationship]:
    previous = {item.name: item for item in prior.relationships} if prior else {}
    all_names = set(names) | set(previous)
    return [
        previous.get(name)
        or GraphRelationship(
            relationship_id=_relationship_id(name),
            name=name,
            semantics="directed",
            created_at=created_at,
            description=_RELATION_NAMES.get(name, name.replace("_", " ").capitalize()),
        )
        for name in sorted(all_names)
    ]


def _relation_name(
    relation_id: str,
    relationships: Sequence[GraphRelationship],
    prior: TemporalGraphSnapshot | None,
) -> str:
    for relation in relationships:
        if relation.relationship_id == relation_id:
            return relation.name
    if prior:
        for relation in prior.relationships:
            if relation.relationship_id == relation_id:
                return relation.name
    return relation_id


def _active_states(
    states: list[GraphEdgeState], as_of: datetime, knowledge_time: datetime
) -> list[GraphEdgeState]:
    return [
        item
        for item in states
        if item.lifecycle_status == "active"
        and item.effective_from <= as_of
        and (item.effective_to is None or as_of < item.effective_to)
        and item.knowledge_from <= knowledge_time
        and (item.knowledge_to is None or knowledge_time < item.knowledge_to)
    ]


def _find_active(
    states: list[GraphEdgeState], source: str, target: str, relation_id: str
) -> GraphEdgeState | None:
    return next(
        (
            item
            for item in states
            if item.source_node_id == source
            and item.target_node_id == target
            and item.relationship_id == relation_id
        ),
        None,
    )


def _dedupe_observations(items: Sequence[EvidenceObservation]) -> list[EvidenceObservation]:
    return list({str(item.observation_id): item for item in items}.values())


def _new_state(
    key: EdgeKey,
    decision: EdgeEligibility,
    observations: Sequence[EvidenceObservation],
    request: GraphPipelineRequest,
    retire: bool = False,
) -> GraphEdgeState:
    source, target, relation_name = key
    evidence_ids = tuple(sorted({str(item.observation_id) for item in observations}))
    quality = max(
        (evidence_quality(item, request.as_of_time) for item in observations), default=0.0
    )
    eid = _edge_state_id(source, target, relation_name, request.knowledge_time, evidence_ids)
    eligible: EligibilityStatus = (
        "eligible"
        if decision.status == "eligible" and not retire
        else ("review_required" if decision.status == "review_required" else "ineligible")
    )
    return GraphEdgeState(
        edge_id=eid,
        created_at=request.knowledge_time,
        relationship_id=decision.relationship_id,
        source_node_id=source,
        target_node_id=target,
        effective_from=request.as_of_time,
        knowledge_from=request.knowledge_time,
        evidence_ids=evidence_ids,
        confidence=decision.confidence,
        economic_exposure=round(decision.confidence if eligible == "eligible" else 0.0, 6),
        propagation_coefficient=round(min(1.0, decision.confidence * quality), 6),
        lifecycle_status="retracted" if retire else "active",
        strategy_eligible=eligible,
        attributes={
            "support_count": decision.support_count,
            "contradiction_count": decision.contradiction_count,
            "independent_sources": decision.independent_sources,
            "last_supported_at": request.as_of_time.isoformat(),
        },
    )


def _replace_state(
    previous: GraphEdgeState,
    decision: EdgeEligibility,
    request: GraphPipelineRequest,
    expired: bool = False,
    decay: float = 1.0,
    observations: Sequence[EvidenceObservation] = (),
) -> GraphEdgeState:
    new_evidence_ids = {str(item.observation_id) for item in observations}
    evidence_ids = tuple(sorted(set(previous.evidence_ids) | new_evidence_ids))
    if expired:
        return previous.model_copy(
            update={
                "created_at": request.knowledge_time,
                "edge_id": _edge_state_id(
                    previous.source_node_id,
                    previous.target_node_id,
                    previous.relationship_id,
                    request.knowledge_time,
                    evidence_ids,
                ),
                "knowledge_from": request.knowledge_time,
                "knowledge_to": None,
                "effective_from": request.as_of_time,
                "effective_to": None,
                "lifecycle_status": "retracted",
                "strategy_eligible": "ineligible",
                "confidence": round(
                    decision.confidence if decision.support_count else previous.confidence * decay,
                    6,
                ),
                "economic_exposure": 0.0,
                "propagation_coefficient": round(previous.propagation_coefficient * decay, 6),
            }
        )
    if decision.support_count == 0 and decision.contradiction_count == 0:
        confidence = round(previous.confidence * decay, 6)
        propagation = round(previous.propagation_coefficient * decay, 6)
    else:
        confidence = decision.confidence
        quality = max(
            (evidence_quality(item, request.as_of_time) for item in observations), default=0.0
        )
        propagation = round(decision.confidence * quality, 6)
    eligible: EligibilityStatus = decision.status
    return GraphEdgeState(
        edge_id=_edge_state_id(
            previous.source_node_id,
            previous.target_node_id,
            previous.relationship_id,
            request.knowledge_time,
            evidence_ids,
        ),
        created_at=request.knowledge_time,
        relationship_id=previous.relationship_id,
        source_node_id=previous.source_node_id,
        target_node_id=previous.target_node_id,
        effective_from=request.as_of_time,
        knowledge_from=request.knowledge_time,
        evidence_ids=evidence_ids,
        confidence=confidence,
        economic_exposure=round(confidence if eligible == "eligible" else 0.0, 6),
        propagation_coefficient=propagation,
        lifecycle_status="active",
        strategy_eligible=eligible,
        attributes={
            **previous.attributes,
            "last_policy_reason": decision.reason,
            "last_supported_at": request.as_of_time.isoformat()
            if decision.support_count
            else previous.attributes.get("last_supported_at"),
        },
    )


def _close_and_append(
    states: list[GraphEdgeState],
    previous: GraphEdgeState,
    current: GraphEdgeState,
    knowledge_time: datetime,
    as_of_time: datetime,
) -> tuple[list[GraphEdgeState], tuple[str, ...]]:
    if knowledge_time <= previous.knowledge_from:
        raise ValueError("knowledge_time must advance when revising an existing edge")
    closed = previous.model_copy(update={"knowledge_to": knowledge_time})
    result = [closed if item.edge_id == previous.edge_id else item for item in states]
    inserted: list[str] = []
    if as_of_time > previous.effective_from:
        historical_id = _edge_state_id(
            previous.source_node_id,
            previous.target_node_id,
            previous.relationship_id,
            knowledge_time,
            (*previous.evidence_ids, "historical"),
        )
        historical = previous.model_copy(
            update={
                "edge_id": historical_id,
                "created_at": knowledge_time,
                "effective_to": as_of_time,
                "knowledge_from": knowledge_time,
                "knowledge_to": None,
            }
        )
        result.append(historical)
        inserted.append(historical.edge_id)
    result.append(current)
    inserted.append(current.edge_id)
    return result, tuple(inserted)


def _edge_state_id(
    source: str, target: str, relationship: str, at: datetime, evidence_ids: Sequence[str]
) -> str:
    material = f"{source}|{target}|{relationship}|{at.isoformat()}|{'|'.join(evidence_ids)}"
    return "edge-" + hashlib.sha256(material.encode()).hexdigest()[:24]


def _make_snapshot(
    request: GraphPipelineRequest,
    prior: TemporalGraphSnapshot | None,
    nodes: Sequence[GraphNode],
    relationships: Sequence[GraphRelationship],
    states: Sequence[GraphEdgeState],
    request_key: str,
) -> TemporalGraphSnapshot:
    universe_id = request.universe.universe_id
    nodes = [
        node.model_copy(update={"properties": {**node.properties, "universe_id": universe_id}})
        for node in nodes
    ]
    snapshot_id = request.request_id or "graph-" + request_key[:24]
    return TemporalGraphSnapshot(
        snapshot_id=snapshot_id,
        workspace_id=request.universe.workspace_id,
        universe_id=universe_id,
        universe_instrument_ids=tuple(
            sorted(item.instrument_id for item in request.universe.instruments)
        ),
        parent_snapshot_id=prior.snapshot_id if prior else None,
        created_at=request.knowledge_time,
        published_at=request.knowledge_time,
        as_of_time=request.as_of_time,
        knowledge_time=request.knowledge_time,
        nodes=tuple(nodes),
        relationships=tuple(relationships),
        edge_states=tuple(states),
        source_run_id=request_key,
    )
