import hashlib
from datetime import UTC, datetime, timedelta

from alpha_workbench.agents.extraction import build_extraction_agent
from alpha_workbench.evidence import (
    DuckDBEvidenceLedger,
    EvidenceObservation,
    ExtractionProvenance,
    SourceDocument,
    TextEvidence,
)
from alpha_workbench.extraction import DocumentPassage, EdgeProposal, EvidenceValidationReport
from alpha_workbench.graph_pipeline import (
    DuckDBGraphInputProvider,
    EvidenceAssessment,
    GraphPipelineRequest,
    bootstrap_graph,
    update_graph,
)
from alpha_workbench.llm.models import FakeLLMClient
from alpha_workbench.product import InstrumentRef, UniverseSpec
from alpha_workbench.temporal_graph.repository import InMemoryTemporalGraphRepository

AS_OF = datetime(2026, 9, 1, tzinfo=UTC)


def _universe() -> UniverseSpec:
    instruments = tuple(
        InstrumentRef(
            instrument_id=f"instrument-{index}",
            symbol=f"C{index}",
            exchange="NASDAQ",
            currency="USD",
            entity_id=f"entity-{index}",
        )
        for index in range(10)
    )
    return UniverseSpec(
        universe_id="locked-ten",
        workspace_id="workspace-1",
        domain="semiconductors",
        instruments=instruments,
        selection_time=AS_OF,
        selection_mode="current",
        selection_method="frozen fixture",
        target_count=10,
    )


def _observation(
    source: str,
    *,
    day: datetime = AS_OF,
    source_id: str = "entity-1",
    target_id: str = "entity-0",
) -> EvidenceObservation:
    text = f"{target_id} relies on {source_id} for an essential component supply agreement."
    return EvidenceObservation(
        idempotency_key=f"{source}:{day.isoformat()}:{source_id}:{target_id}",
        document=SourceDocument(
            source_kind="sec_filing" if "primary" in source else "web_discovery",
            source_tier="primary" if "primary" in source else "discovery",
            source_adapter="fixture",
            source_url=f"https://{source}.example.test/article",
            content_sha256=hashlib.sha256(source.encode()).hexdigest(),
            issuer_entity_id=target_id,
            observed_at=day,
            available_at=day,
            retrieved_at=day,
            usage_note="offline graph fixture",
        ),
        mentioned_entity_ids=(target_id, source_id),
        payload=TextEvidence(
            text=text,
            exact_quote=text,
            character_start=0,
            character_end=len(text),
        ),
        extraction=ExtractionProvenance(
            extractor_name="fixture", extractor_version="1", run_id="pipeline-tests"
        ),
    )


def _proposal(observation: EvidenceObservation, source_id="entity-0", target_id="entity-1"):
    quote = observation.payload.exact_quote
    proposal = EdgeProposal(
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type="manufacturing_dependency",
        evidence_quote=quote,
        passage=DocumentPassage(
            snapshot_sha256=observation.document.content_sha256,
            source_url=observation.document.source_url,
            start_offset=0,
            end_offset=len(quote),
            text=quote,
            matching_keywords=["supply agreement"],
            observation_id=str(observation.observation_id),
        ),
        rationale="Fixture proposal from exact source text.",
        suggested_confidence=0.99,
    )
    return proposal, EvidenceValidationReport(
        proposal_id=proposal.id,
        verdict="pass",
        reasons=["fixture passed deterministic validation"],
    )


def _request(
    observations,
    *,
    trigger="bootstrap",
    assessments=(),
    extra_proposals=(),
    at=AS_OF,
    knowledge=None,
):
    first = observations[0]
    proposal, report = _proposal(first)
    proposals = (proposal, *extra_proposals)
    reports = [report]
    for item in extra_proposals:
        reports.append(
            EvidenceValidationReport(proposal_id=item.id, verdict="pass", reasons=["fixture pass"])
        )
    explicit_assessment_ids = {item.observation_id for item in assessments}
    all_assessments = list(assessments)
    proposals_by_observation = {
        item.passage.observation_id: item for item in proposals if item.passage.observation_id
    }
    for observation in observations[1:]:
        observation_id = str(observation.observation_id)
        if observation_id not in explicit_assessment_ids:
            proposal_for_observation = proposals_by_observation.get(observation_id)
            all_assessments.append(
                EvidenceAssessment(
                    observation_id=observation_id,
                    source_entity_id=proposal_for_observation.source_entity_id
                    if proposal_for_observation
                    else "entity-0",
                    target_entity_id=proposal_for_observation.target_entity_id
                    if proposal_for_observation
                    else "entity-1",
                    relationship_type=proposal_for_observation.relationship_type
                    if proposal_for_observation
                    else "manufacturing_dependency",
                    stance="support",
                )
            )
    return GraphPipelineRequest(
        universe=_universe(),
        as_of_time=at,
        knowledge_time=knowledge or at,
        observations=tuple(observations),
        validated_proposals=proposals,
        validation_reports=tuple(reports),
        assessments=tuple(all_assessments),
        trigger=trigger,
    )


def test_bootstrap_builds_locked_ten_company_graph_without_review_gate() -> None:
    observations = [_observation("primary-a"), _observation("discovery-b")]
    repository = InMemoryTemporalGraphRepository()
    snapshot, report = bootstrap_graph(_request(observations), repository)

    assert len(snapshot.universe_instrument_ids) == 10
    assert sum(node.kind == "instrument" for node in snapshot.nodes) == 10
    assert sum(node.kind == "entity" for node in snapshot.nodes) == 10
    edge = snapshot.edge_states[0]
    assert edge.strategy_eligible == "eligible"
    assert edge.evidence_ids == tuple(sorted(str(item.observation_id) for item in observations))
    assert report.published is True


def test_missing_instrument_entity_ids_derive_distinct_stable_entity_nodes() -> None:
    base = _universe()
    universe = base.model_copy(
        update={
            "universe_id": "missing-entity-ids",
            "instruments": tuple(
                item.model_copy(update={"entity_id": None}) for item in base.instruments
            ),
        }
    )
    snapshot, _ = bootstrap_graph(
        GraphPipelineRequest(
            universe=universe,
            as_of_time=AS_OF,
            knowledge_time=AS_OF,
        ),
        InMemoryTemporalGraphRepository(),
    )
    node_ids = [node.node_id for node in snapshot.nodes]
    assert len(node_ids) == len(set(node_ids))
    assert {node.node_id for node in snapshot.nodes if node.kind == "entity"} == {
        f"entity:instrument-{index}" for index in range(10)
    }
    assert len(snapshot.visible_edge_states()) == 0


def test_optional_extraction_composition_accepts_fake_model_and_policy_sets_eligibility(
    tmp_path,
) -> None:
    observation = _observation("primary-a")
    quote = observation.payload.exact_quote
    fake_model = FakeLLMClient(
        {
            "source_entity_id": "entity-0",
            "target_entity_id": "entity-1",
            "relationship_type": "manufacturing_dependency",
            "evidence_quote": quote,
            "rationale": "The quoted text describes a supply dependency.",
            # The suggestion is intentionally high; it must not grant eligibility.
            "suggested_confidence": 1.0,
        }
    )
    universe = _universe()
    agent = build_extraction_agent(
        cache_dir=tmp_path,
        llm=fake_model,
        sec_user_agent="Agentic Alpha CI test contact@example.test",
        known_entities={
            alias
            for item in universe.instruments
            for alias in (item.entity_id or item.instrument_id, item.symbol)
        },
    )
    ledger_path = tmp_path / "evidence.duckdb"
    with DuckDBEvidenceLedger(ledger_path) as ledger:
        ledger.append(observation)

    provider = DuckDBGraphInputProvider(
        ledger_path, extraction_agent_factory=lambda _universe: agent
    )
    inputs = provider.load(universe, as_of_time=AS_OF, knowledge_time=AS_OF)
    assert len(inputs.proposals) == 1
    assert inputs.validation_reports[0].verdict == "pass"

    snapshot, _ = bootstrap_graph(
        GraphPipelineRequest(
            universe=universe,
            as_of_time=AS_OF,
            knowledge_time=AS_OF,
            observations=inputs.observations,
            validated_proposals=inputs.proposals,
            validation_reports=inputs.validation_reports,
        ),
        InMemoryTemporalGraphRepository(),
    )
    assert snapshot.edge_states[0].confidence < 1.0
    assert snapshot.edge_states[0].strategy_eligible == "ineligible"


def test_external_entities_mentioned_by_available_evidence_remain_context_nodes() -> None:
    observation = _observation("primary-a", target_id="outside-supplier")
    proposal, report = _proposal(observation, source_id="outside-supplier", target_id="entity-0")
    request = GraphPipelineRequest(
        universe=_universe(),
        as_of_time=AS_OF,
        knowledge_time=AS_OF,
        observations=(observation,),
        validated_proposals=(proposal,),
        validation_reports=(report,),
    )
    snapshot, _ = bootstrap_graph(request, InMemoryTemporalGraphRepository())
    context = next(node for node in snapshot.nodes if node.node_id == "external:outside-supplier")
    assert context.kind == "external_context"
    assert snapshot.edge_states[0].source_node_id == context.node_id


def test_single_source_is_ineligible_and_independent_corroboration_promotes() -> None:
    repository = InMemoryTemporalGraphRepository()
    one = _observation("primary-a")
    first, _ = bootstrap_graph(_request([one]), repository)
    assert first.edge_states[0].strategy_eligible == "ineligible"

    second = _observation("discovery-b")
    update, report = update_graph(
        _request(
            [one, second],
            trigger="event",
            at=AS_OF + timedelta(days=1),
            knowledge=AS_OF + timedelta(days=1),
        ),
        repository,
    )
    current = update.visible_edge_states()[0]
    assert current.strategy_eligible == "eligible"
    assert len(current.evidence_ids) == 2
    assert report.affected_edge_ids


def test_symbol_and_caller_aliases_resolve_to_universe_entity_ids() -> None:
    observations = [_observation("primary-a"), _observation("discovery-b")]
    request = _request(observations)
    original = request.validated_proposals[0]
    alias_proposal = original.model_copy(
        update={"source_entity_id": "C0", "target_entity_id": "supplier alias"}
    )
    report = request.validation_reports[0].model_copy(update={"proposal_id": alias_proposal.id})
    request = request.model_copy(
        update={
            "validated_proposals": (alias_proposal,),
            "validation_reports": (report,),
            "aliases": {"supplier alias": "C1"},
        }
    )

    snapshot, _ = bootstrap_graph(request, InMemoryTemporalGraphRepository())

    edge = snapshot.edge_states[0]
    assert (edge.source_node_id, edge.target_node_id) == (
        "entity:entity-0",
        "entity:entity-1",
    )
    assert edge.strategy_eligible == "eligible"


def test_conflicting_evidence_holds_strategy_eligibility() -> None:
    observations = [
        _observation("primary-a"),
        _observation("discovery-b"),
        _observation("primary-c"),
    ]
    contradiction = EvidenceAssessment(
        observation_id=str(observations[2].observation_id),
        source_entity_id="entity-0",
        target_entity_id="entity-1",
        relationship_type="manufacturing_dependency",
        stance="contradict",
    )
    snapshot, _ = bootstrap_graph(
        _request(observations, assessments=[contradiction]), InMemoryTemporalGraphRepository()
    )
    assert snapshot.edge_states[0].strategy_eligible == "review_required"
    assert snapshot.edge_states[0].economic_exposure == 0


def test_future_evidence_is_excluded_from_point_in_time_eligibility() -> None:
    first = _observation("primary-a")
    future = _observation("discovery-b", day=AS_OF + timedelta(days=5))
    support = EvidenceAssessment(
        observation_id=str(future.observation_id),
        source_entity_id="entity-0",
        target_entity_id="entity-1",
        relationship_type="manufacturing_dependency",
        stance="support",
    )
    snapshot, report = bootstrap_graph(
        _request([first, future], assessments=[support]), InMemoryTemporalGraphRepository()
    )
    assert snapshot.edge_states[0].strategy_eligible == "ineligible"
    assert report.excluded_observation_ids == (str(future.observation_id),)
    assert str(future.observation_id) not in snapshot.edge_states[0].evidence_ids


def test_evidence_retrieved_after_knowledge_cutoff_is_excluded() -> None:
    available = _observation("discovery-b")
    retrieved_late = available.model_copy(
        update={
            "idempotency_key": "late-retrieval",
            "document": available.document.model_copy(
                update={"retrieved_at": AS_OF + timedelta(days=1)}
            ),
        }
    )
    primary = _observation("primary-a")
    snapshot, report = bootstrap_graph(
        _request([primary, retrieved_late]), InMemoryTemporalGraphRepository()
    )
    assert str(retrieved_late.observation_id) in report.excluded_observation_ids
    assert str(retrieved_late.observation_id) not in snapshot.edge_states[0].evidence_ids


def test_replay_is_idempotent_and_history_remains_reproducible() -> None:
    repository = InMemoryTemporalGraphRepository()
    observations = [_observation("primary-a"), _observation("discovery-b")]
    request = _request(observations)
    first, _ = bootstrap_graph(request, repository)
    replay, replay_report = bootstrap_graph(request, repository)
    assert replay.snapshot_id == first.snapshot_id
    assert replay_report.idempotent_replay
    assert len(repository.list("workspace-1")) == 1

    future = _observation("primary-c", day=AS_OF + timedelta(days=2))
    retirement = [
        EvidenceAssessment(
            observation_id=str(future.observation_id),
            source_entity_id="entity-0",
            target_entity_id="entity-1",
            relationship_type="manufacturing_dependency",
            stance="retire",
        ),
        EvidenceAssessment(
            observation_id=str(observations[1].observation_id),
            source_entity_id="entity-0",
            target_entity_id="entity-1",
            relationship_type="manufacturing_dependency",
            stance="retire",
        ),
    ]
    # Retirement at a later point in knowledge/effective time closes the active state.
    retired_obs = _observation("primary-c", day=AS_OF + timedelta(days=3))
    retirement[0] = retirement[0].model_copy(
        update={"observation_id": str(retired_obs.observation_id)}
    )
    second, _ = update_graph(
        _request(
            [retired_obs, observations[1]],
            trigger="event",
            assessments=retirement,
            at=AS_OF + timedelta(days=3),
            knowledge=AS_OF + timedelta(days=3),
        ),
        repository,
    )
    retired_state = second.visible_edge_states()[0]
    assert retired_state.lifecycle_status == "retracted"
    assert retired_state.strategy_eligible == "ineligible"
    replay_old = repository.replay("workspace-1", as_of_time=AS_OF, knowledge_time=AS_OF)
    assert replay_old.visible_edge_states()[0].strategy_eligible == "eligible"
    replay_latest_past = repository.replay(
        "workspace-1",
        as_of_time=AS_OF + timedelta(days=1),
        knowledge_time=AS_OF + timedelta(days=3),
    )
    assert replay_latest_past.visible_edge_states()[0].strategy_eligible == "eligible"


def test_nightly_decay_retires_stale_edge() -> None:
    repository = InMemoryTemporalGraphRepository()
    observations = [_observation("primary-a"), _observation("discovery-b")]
    first, _ = bootstrap_graph(_request(observations), repository)
    later = AS_OF + timedelta(days=900)
    second, _ = update_graph(
        GraphPipelineRequest(
            universe=_universe(),
            as_of_time=later,
            knowledge_time=later,
            trigger="nightly",
        ),
        repository,
    )
    assert first.edge_states[0].lifecycle_status == "active"
    assert second.edge_states[-1].lifecycle_status == "retracted"
    assert second.edge_states[-1].strategy_eligible == "ineligible"


def test_event_request_changes_only_its_affected_logical_edge() -> None:
    observations = [
        _observation("primary-a", source_id="entity-0", target_id="entity-1"),
        _observation("discovery-b", source_id="entity-0", target_id="entity-1"),
        _observation("primary-c", source_id="entity-2", target_id="entity-3"),
        _observation("discovery-d", source_id="entity-2", target_id="entity-3"),
    ]
    second_proposal, _ = _proposal(observations[2], source_id="entity-2", target_id="entity-3")
    repository = InMemoryTemporalGraphRepository()
    initial, _ = bootstrap_graph(
        _request(observations, extra_proposals=[second_proposal]), repository
    )
    unaffected = next(
        state for state in initial.edge_states if state.source_node_id == "entity:entity-2"
    )

    event = _observation(
        "event-z", day=AS_OF + timedelta(days=1), source_id="entity-0", target_id="entity-1"
    )
    contradiction = EvidenceAssessment(
        observation_id=str(event.observation_id),
        source_entity_id="entity-0",
        target_entity_id="entity-1",
        relationship_type="manufacturing_dependency",
        stance="contradict",
    )
    request = GraphPipelineRequest(
        universe=_universe(),
        as_of_time=AS_OF + timedelta(days=1),
        knowledge_time=AS_OF + timedelta(days=1),
        observations=(event,),
        assessments=(contradiction,),
        trigger="event",
    )
    updated, report = update_graph(request, repository)

    assert report.affected_edge_ids
    assert any(state.edge_id == unaffected.edge_id for state in updated.edge_states)
    assert len(updated.visible_edge_states()) == 2
