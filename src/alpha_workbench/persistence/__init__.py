"""Persistence interfaces for immutable product records."""

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
]
