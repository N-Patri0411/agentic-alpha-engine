"""Persistence interfaces for immutable product records."""

from alpha_workbench.temporal_graph import (
    InMemoryTemporalGraphRepository,
    PostgresTemporalGraphRepository,
    TemporalGraphRepository,
)

from .repositories import (
    ImmutableVersionError,
    InMemoryVersionedRepository,
    PostgresProductRepository,
    ProductRepository,
    RepositoryNotFoundError,
)

__all__ = [
    "ImmutableVersionError",
    "InMemoryVersionedRepository",
    "PostgresProductRepository",
    "ProductRepository",
    "RepositoryNotFoundError",
    "InMemoryTemporalGraphRepository",
    "PostgresTemporalGraphRepository",
    "TemporalGraphRepository",
]
