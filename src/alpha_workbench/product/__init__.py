"""Production product contracts for workspaces, strategies, and readiness.

The models in this package are deliberately independent of API, worker, and
database implementations.  They form the versioned boundary between those
components and existing research/evidence records.
"""

from .canonical import canonical_json, canonical_payload, content_sha256
from .contracts import (
    ContractBase,
    DomainWorkspace,
    InstrumentRef,
    ProviderCapability,
    ReadinessCheck,
    ReadinessReport,
    StrategyPackage,
    StrategyRun,
    StrategySpec,
    UniverseSpec,
)

__all__ = [
    "DomainWorkspace",
    "ContractBase",
    "InstrumentRef",
    "ProviderCapability",
    "ReadinessCheck",
    "ReadinessReport",
    "StrategyPackage",
    "StrategyRun",
    "StrategySpec",
    "UniverseSpec",
    "canonical_json",
    "canonical_payload",
    "content_sha256",
]
