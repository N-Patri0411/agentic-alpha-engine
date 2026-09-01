"""Standalone, typed agent callables wired together only after isolated tests pass."""

from .alpha_generator import AlphaGeneratorAgent
from .backtester_agent import BacktesterAgent
from .extraction import ExtractionAgent, FilingExtractionRequest, build_extraction_agent
from .gatekeeper import GatekeeperAgent
from .monitor import MonitorAgent
from .orchestrator import OrchestratorAgent
from .portfolio import PortfolioOptimiserAgent
from .research import ResearchAgent

__all__ = [
    "AlphaGeneratorAgent",
    "BacktesterAgent",
    "ExtractionAgent",
    "FilingExtractionRequest",
    "GatekeeperAgent",
    "MonitorAgent",
    "OrchestratorAgent",
    "PortfolioOptimiserAgent",
    "ResearchAgent",
    "build_extraction_agent",
]
