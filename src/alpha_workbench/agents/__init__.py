"""Standalone, typed agent callables wired together only after isolated tests pass."""

from .alpha_generator import AlphaGeneratorAgent
from .backtester_agent import BacktesterAgent
from .extraction import (
    ExtractionAgent,
    FilingExtractionRequest,
    ObservationExtractionRequest,
    build_extraction_agent,
)
from .extraction_graph_workflow import ExtractionGraphWorkflow
from .gatekeeper import GatekeeperAgent
from .graph_adjudicator import GraphAdjudicatorAgent
from .monitor import MonitorAgent
from .orchestrator import OrchestratorAgent
from .portfolio import PortfolioOptimiserAgent
from .research import ResearchAgent

__all__ = [
    "AlphaGeneratorAgent",
    "BacktesterAgent",
    "ExtractionAgent",
    "ExtractionGraphWorkflow",
    "FilingExtractionRequest",
    "GraphAdjudicatorAgent",
    "GatekeeperAgent",
    "MonitorAgent",
    "OrchestratorAgent",
    "ObservationExtractionRequest",
    "PortfolioOptimiserAgent",
    "ResearchAgent",
    "build_extraction_agent",
]
