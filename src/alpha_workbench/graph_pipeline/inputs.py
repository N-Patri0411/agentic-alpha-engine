"""Evidence input providers for graph jobs; all external inputs are injectable."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from alpha_workbench.agents.extraction import (
    ExtractionAgent,
    ObservationExtractionRequest,
)
from alpha_workbench.evidence import DuckDBEvidenceLedger, EvidenceObservation
from alpha_workbench.extraction import EdgeProposal, EvidenceValidationReport
from alpha_workbench.product import UniverseSpec

from .contracts import EvidenceAssessment


@dataclass(frozen=True)
class GraphInputs:
    observations: tuple[EvidenceObservation, ...] = ()
    proposals: tuple[EdgeProposal, ...] = ()
    validation_reports: tuple[EvidenceValidationReport, ...] = ()
    assessments: tuple[EvidenceAssessment, ...] = ()
    aliases: dict[str, str] | None = None
    warnings: tuple[str, ...] = ()


class GraphInputProvider(Protocol):
    """Loads point-in-time evidence without exposing storage to job handlers."""

    def load(
        self,
        universe: UniverseSpec,
        *,
        as_of_time: datetime,
        knowledge_time: datetime,
    ) -> GraphInputs: ...


class EmptyGraphInputProvider:
    """Explicit offline provider used by isolated app/test dependencies."""

    def load(
        self,
        universe: UniverseSpec,
        *,
        as_of_time: datetime,
        knowledge_time: datetime,
    ) -> GraphInputs:
        del universe, as_of_time, knowledge_time
        return GraphInputs(warnings=("No evidence input provider is configured.",))


class DuckDBGraphInputProvider:
    """Reads existing evidence rows and optionally runs the injected ExtractionAgent."""

    def __init__(
        self,
        path: Path,
        *,
        extraction_agent_factory: Callable[[UniverseSpec], ExtractionAgent | None] | None = None,
    ) -> None:
        self.path = path
        self.extraction_agent_factory = extraction_agent_factory

    def load(
        self,
        universe: UniverseSpec,
        *,
        as_of_time: datetime,
        knowledge_time: datetime,
    ) -> GraphInputs:
        if not self.path.exists():
            return GraphInputs(warnings=("Evidence ledger is not present; graph is node-only.",))
        with DuckDBEvidenceLedger(self.path) as ledger:
            observations = tuple(ledger.observations_as_of(as_of_time))
        eligible = tuple(
            item
            for item in observations
            if item.document.available_at <= as_of_time
            and item.document.retrieved_at <= knowledge_time
        )
        if not eligible:
            return GraphInputs(
                observations=(),
                warnings=("No evidence was available at the requested graph cutoffs.",),
            )
        if self.extraction_agent_factory is None:
            return GraphInputs(
                observations=eligible,
                warnings=("Text evidence was retained but no ExtractionAgent is configured.",),
            )

        agent = self.extraction_agent_factory(universe)
        if agent is None:
            return GraphInputs(
                observations=eligible,
                warnings=("Text evidence was retained but no ExtractionAgent is configured.",),
            )
        known_entities = {
            alias
            for item in universe.instruments
            for alias in (
                item.entity_id or item.instrument_id,
                item.instrument_id,
                item.symbol,
                *item.provider_symbols.values(),
            )
        }
        known_entities.update(
            mentioned for observation in eligible for mentioned in observation.mentioned_entity_ids
        )
        report = agent.run_observations(
            ObservationExtractionRequest(observations=list(eligible), known_entities=known_entities)
        )
        proposals = tuple(item for item in report.outcomes if isinstance(item, EdgeProposal))
        return GraphInputs(
            observations=tuple(report.observations),
            proposals=proposals,
            validation_reports=tuple(report.validations),
            warnings=()
            if proposals
            else ("Evidence produced no validated relationship proposals.",),
        )


def configured_extraction_agent(universe: UniverseSpec) -> ExtractionAgent | None:
    """Create the existing model-agnostic extractor only when explicitly enabled."""
    enabled = os.environ.get("ALPHA_GRAPH_EXTRACTION_ENABLED", "").casefold() in {
        "1",
        "true",
        "yes",
    }
    if not enabled:
        return None
    from alpha_workbench.agents.extraction import build_extraction_agent
    from alpha_workbench.graph_pipeline.service import _stable_entity_node_id
    from alpha_workbench.llm.models import create_llm, load_model_config

    known = {
        alias
        for item in universe.instruments
        for alias in (
            _stable_entity_node_id(item.entity_id or item.instrument_id),
            item.entity_id or item.instrument_id,
            item.instrument_id,
            item.symbol,
            *item.provider_symbols.values(),
        )
    }
    config_path = Path(os.environ.get("ALPHA_MODELS_CONFIG", "config/models.yaml"))
    llm = create_llm(load_model_config(config_path, "extraction"))
    return build_extraction_agent(
        cache_dir=Path("data/private/extraction-cache"), llm=llm, known_entities=known
    )


def default_graph_input_provider() -> DuckDBGraphInputProvider:
    path = Path(os.environ.get("ALPHA_EVIDENCE_DB", "data/private/evidence.duckdb"))
    return DuckDBGraphInputProvider(path, extraction_agent_factory=configured_extraction_agent)
