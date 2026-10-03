"""Immutable temporal graph contracts and repositories (graph v2)."""

from .analysis import BoundedGraphAnalysis
from .contracts import (
    GraphEdgeState,
    GraphNode,
    GraphPublicationReceipt,
    GraphRelationship,
    GraphSnapshotDiff,
    TemporalGraphSnapshot,
)
from .repository import (
    GraphSnapshotNotFoundError,
    ImmutableGraphSnapshotError,
    InMemoryTemporalGraphRepository,
    PostgresTemporalGraphRepository,
    TemporalGraphRepository,
    diff_snapshots,
)

__all__ = [
    "GraphEdgeState",
    "BoundedGraphAnalysis",
    "GraphNode",
    "GraphPublicationReceipt",
    "GraphRelationship",
    "GraphSnapshotDiff",
    "GraphSnapshotNotFoundError",
    "ImmutableGraphSnapshotError",
    "InMemoryTemporalGraphRepository",
    "PostgresTemporalGraphRepository",
    "TemporalGraphRepository",
    "TemporalGraphSnapshot",
    "diff_snapshots",
]
