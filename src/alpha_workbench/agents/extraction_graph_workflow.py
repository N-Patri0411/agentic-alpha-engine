"""The first real A2A workflow: validated extraction to graph adjudication."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ..a2a import (
    A2AMessage,
    DuckDBMessageBus,
    ExtractionCommandPayload,
    GraphReviewRequestPayload,
)
from ..evidence import EvidenceObservation, TextEvidence
from ..extraction import EdgeProposal
from ..graph_registry import GraphSnapshot
from .contracts import AgentName, ArtifactRef
from .extraction import ExtractionAgent, ObservationExtractionRequest
from .graph_adjudicator import GraphAdjudicationReport, GraphAdjudicatorAgent


class ExtractionGraphWorkflow:
    """Moves validated drafts through a durable local inbox without direct calls.

    This bounded workflow deliberately has only two transitions:
    orchestrator -> extraction -> graph_adjudicator. The graph receives only
    observations linked to a deterministic validation pass.
    """

    def __init__(
        self,
        bus: DuckDBMessageBus,
        extraction: ExtractionAgent,
        adjudicator: GraphAdjudicatorAgent,
    ) -> None:
        self._bus = bus
        self._extraction = extraction
        self._adjudicator = adjudicator

    def enqueue_extraction(
        self,
        *,
        trace_id: str,
        run_id: str,
        observations: list[EvidenceObservation],
        known_entities: set[str],
        as_of_time: datetime,
    ) -> A2AMessage:
        payload = ExtractionCommandPayload(
            observations=observations, known_entities=known_entities
        )
        return self._publish(
            trace_id=trace_id,
            run_id=run_id,
            sender="orchestrator",
            recipient="extraction",
            message_type="command",
            payload={
                "extraction": payload.model_dump(mode="json"),
                "as_of_time": as_of_time.isoformat(),
            },
        )

    def process_extraction(self, message: A2AMessage) -> A2AMessage | None:
        if message.recipient != "extraction" or message.message_type != "command":
            raise ValueError("expected an extraction command message")
        raw_payload = message.typed_payload.get("extraction")
        if not isinstance(raw_payload, dict):
            raise ValueError("extraction message is missing its typed payload")
        raw_as_of = message.typed_payload.get("as_of_time")
        if not isinstance(raw_as_of, str):
            raise ValueError("extraction message is missing as_of_time")
        payload = ExtractionCommandPayload.model_validate(raw_payload)
        as_of_time = datetime.fromisoformat(raw_as_of)
        report = self._extraction.run_observations(
            ObservationExtractionRequest(
                observations=payload.observations, known_entities=payload.known_entities
            )
        )
        text_observations = [
            observation
            for observation in payload.observations
            if isinstance(observation.payload, TextEvidence)
        ]
        if len(text_observations) != len(report.outcomes):
            raise RuntimeError("extraction did not produce one outcome per text observation")
        validations_by_proposal = {
            validation.proposal_id: validation for validation in report.validations
        }
        selected_observations = []
        selected_proposals: list[EdgeProposal] = []
        selected_validations = []
        for observation, outcome in zip(text_observations, report.outcomes, strict=True):
            if not isinstance(outcome, EdgeProposal):
                continue
            validation = validations_by_proposal.get(outcome.id)
            if validation is None or validation.verdict != "pass":
                continue
            selected_observations.append(observation)
            selected_proposals.append(outcome)
            selected_validations.append(validation)
        self._bus.acknowledge(str(message.message_id))
        if not selected_proposals:
            self._publish(
                trace_id=message.trace_id,
                run_id=message.run_id,
                sender="extraction",
                recipient="orchestrator",
                message_type="result",
                payload={
                    "status": "no_validated_proposals",
                    "input_message_id": str(message.message_id),
                },
            )
            return None
        graph_payload = GraphReviewRequestPayload(
            as_of_time=as_of_time,
            observations=selected_observations,
            validated_proposals=selected_proposals,
            validation_reports=selected_validations,
        )
        return self._publish(
            trace_id=message.trace_id,
            run_id=message.run_id,
            sender="extraction",
            recipient="graph_adjudicator",
            message_type="review_request",
            payload={"graph_review": graph_payload.model_dump(mode="json")},
        )

    def process_graph(
        self,
        message: A2AMessage,
        *,
        current_snapshot: GraphSnapshot,
        next_snapshot_id: str,
        snapshot_path: Path,
    ) -> GraphAdjudicationReport:
        if message.recipient != "graph_adjudicator" or message.message_type != "review_request":
            raise ValueError("expected a graph-adjudication review message")
        raw_payload = message.typed_payload.get("graph_review")
        if not isinstance(raw_payload, dict):
            raise ValueError("graph review message is missing its typed payload")
        payload = GraphReviewRequestPayload.model_validate(raw_payload)
        report = self._adjudicator.adjudicate_and_publish(
            observations=payload.observations,
            current_snapshot=current_snapshot,
            as_of_time=payload.as_of_time,
            next_snapshot_id=next_snapshot_id,
            snapshot_path=snapshot_path,
            validated_proposals=payload.validated_proposals,
        )
        snapshot_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        self._bus.acknowledge(str(message.message_id))
        self._publish(
            trace_id=message.trace_id,
            run_id=message.run_id,
            sender="graph_adjudicator",
            recipient="orchestrator",
            message_type="result",
            artifacts=[
                ArtifactRef(
                    id=next_snapshot_id, kind="graph_snapshot", sha256=snapshot_hash
                )
            ],
            payload={"graph_adjudication": report.model_dump(mode="json")},
        )
        return report

    def _publish(
        self,
        *,
        trace_id: str,
        run_id: str,
        sender: AgentName,
        recipient: AgentName,
        message_type: Literal["command", "result", "review_request", "review_decision", "error"],
        payload: dict[str, object],
        artifacts: list[ArtifactRef] | None = None,
    ) -> A2AMessage:
        material = f"{trace_id}:{run_id}:{sender}:{recipient}:{message_type}:{payload}"
        message = A2AMessage(
            trace_id=trace_id,
            run_id=run_id,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            created_at=datetime.now(UTC),
            idempotency_key="a2a:" + hashlib.sha256(material.encode()).hexdigest(),
            artifact_references=artifacts or [],
            typed_payload=payload,
        )
        if not self._bus.publish(message):
            raise RuntimeError("duplicate workflow message was not delivered")
        return message
