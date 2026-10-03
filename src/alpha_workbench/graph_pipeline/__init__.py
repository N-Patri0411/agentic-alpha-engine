"""Autonomous graph lifecycle policy and service APIs."""

from alpha_workbench.temporal_graph.repository import TemporalGraphRepository

from .contracts import (
    EdgeEligibility,
    EvidenceAssessment,
    GraphPipelineReport,
    GraphPipelineRequest,
)
from .inputs import (
    DuckDBGraphInputProvider,
    EmptyGraphInputProvider,
    GraphInputProvider,
    GraphInputs,
    default_graph_input_provider,
)
from .jobs import event_request, graph_refresh_handler, nightly_request, run_graph_pipeline_job
from .service import bootstrap_graph, update_graph

__all__ = [
    "EdgeEligibility",
    "EvidenceAssessment",
    "GraphPipelineReport",
    "GraphPipelineRequest",
    "GraphInputProvider",
    "GraphInputs",
    "DuckDBGraphInputProvider",
    "EmptyGraphInputProvider",
    "TemporalGraphRepository",
    "bootstrap_graph",
    "event_request",
    "graph_refresh_handler",
    "default_graph_input_provider",
    "nightly_request",
    "run_graph_pipeline_job",
    "update_graph",
]
