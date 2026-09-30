"""Database-neutral repositories for Wave 1 product contracts.

The Postgres implementation intentionally accepts a DB-API connection instead
of importing a driver.  Deployments may choose psycopg or psycopg2 while the
offline application and test suite can use the in-memory repository.
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, cast

from pydantic import TypeAdapter

from alpha_workbench.product.canonical import canonical_json
from alpha_workbench.product.contracts import (
    ContractBase,
    DomainWorkspace,
    ProviderCapability,
    ReadinessReport,
    StrategyPackage,
    StrategyRun,
    StrategySpec,
    UniverseSpec,
)


class RepositoryNotFoundError(KeyError):
    """Raised when a requested immutable record does not exist."""


class ImmutableVersionError(ValueError):
    """Raised when a versioned row would be overwritten with different data."""


class DBConnection(Protocol):
    """Small subset of a DB-API connection needed by the repository."""

    def cursor(self) -> Any: ...

    def commit(self) -> Any: ...


T = TypeVar("T", bound=ContractBase)


class ProductRepository(Protocol):
    """Persistence boundary used by the API and workspace job handlers."""

    def put(self, record: DomainWorkspace) -> DomainWorkspace: ...

    def list_workspaces(self, *, latest_only: bool = True) -> tuple[DomainWorkspace, ...]: ...

    def latest_workspace(self, workspace_id: str) -> DomainWorkspace: ...


def _identity(record: ContractBase) -> tuple[str, int]:
    """Get the stable identifier/version pair from a versioned contract."""

    for field in (
        "workspace_id",
        "universe_id",
        "strategy_id",
        "run_id",
        "package_id",
        "provider_id",
        "readiness_id",
    ):
        value = getattr(record, field, None)
        if value:
            return str(value), record.version
    raise TypeError(f"{type(record).__name__} has no versioned identity")


class InMemoryVersionedRepository(Generic[T]):
    """Offline repository with the same append-only semantics as Postgres."""

    def __init__(self) -> None:
        self._records: dict[tuple[type[ContractBase], str, int], ContractBase] = {}

    def put(self, record: T) -> T:
        identifier, version = _identity(record)
        key = (type(record), identifier, version)
        existing = self._records.get(key)
        if existing is not None:
            if existing.content_sha256() != record.content_sha256():
                raise ImmutableVersionError(
                    f"{type(record).__name__} {identifier} version {version} is immutable"
                )
            return cast(T, existing)
        self._records[key] = record
        return record

    def get(self, record_type: type[T], identifier: str, version: int = 1) -> T:
        record = self._records.get((record_type, identifier, version))
        if record is None:
            raise RepositoryNotFoundError((record_type.__name__, identifier, version))
        return cast(T, record)

    def list_versions(self, record_type: type[T], identifier: str) -> tuple[T, ...]:
        records = [
            value
            for (kind, record_id, _), value in self._records.items()
            if kind is record_type and record_id == identifier
        ]
        return tuple(sorted((cast(T, item) for item in records), key=lambda item: item.version))

    def list_workspaces(self, *, latest_only: bool = True) -> tuple[DomainWorkspace, ...]:
        """List workspaces in stable ID/version order."""

        records = [
            cast(DomainWorkspace, value)
            for (kind, _, _), value in self._records.items()
            if kind is DomainWorkspace
        ]
        if latest_only:
            latest: dict[str, DomainWorkspace] = {}
            for workspace in records:
                prior = latest.get(workspace.workspace_id)
                if prior is None or workspace.version > prior.version:
                    latest[workspace.workspace_id] = workspace
            records = list(latest.values())
        return tuple(sorted(records, key=lambda item: (item.workspace_id, item.version)))

    def latest_workspace(self, workspace_id: str) -> DomainWorkspace:
        """Return the latest workspace version or raise a repository error."""

        for workspace in self.list_workspaces(latest_only=True):
            if workspace.workspace_id == workspace_id:
                return workspace
        raise RepositoryNotFoundError((DomainWorkspace.__name__, workspace_id))


class PostgresProductRepository:
    """DB-API repository for product records and append-only job events."""

    _TABLES: dict[type[ContractBase], tuple[str, str]] = {
        DomainWorkspace: ("product_workspaces", "workspace_id"),
        UniverseSpec: ("product_universe_versions", "universe_id"),
        ProviderCapability: ("product_provider_capabilities", "provider_id"),
        StrategySpec: ("product_strategy_versions", "strategy_id"),
        StrategyRun: ("product_strategy_runs", "run_id"),
        StrategyPackage: ("product_strategy_packages", "package_id"),
        ReadinessReport: ("product_readiness_reports", "readiness_id"),
    }

    def __init__(self, connection: DBConnection) -> None:
        self._connection = connection

    def _row(self, record: ContractBase) -> tuple[str, str, int, str, str]:
        identifier, version = _identity(record)
        return (
            identifier,
            record.schema_version,
            version,
            record.content_sha256(),
            canonical_json(record),
        )

    def put(self, record: T) -> T:
        if type(record) not in self._TABLES:
            raise TypeError(f"unsupported product record: {type(record).__name__}")
        table, id_column = self._TABLES[type(record)]
        identifier, schema_version, version, digest, payload = self._row(record)
        cursor = self._connection.cursor()
        cursor.execute(
            f"SELECT content_sha256 FROM {table} "
            f"WHERE {id_column} = %s AND version = %s",
            (identifier, version),
        )
        existing = cursor.fetchone()
        if existing is not None:
            existing_digest = str(existing[0])
            if existing_digest != digest:
                raise ImmutableVersionError(
                    f"{table} {identifier} version {version} is immutable"
                )
            return record
        cursor.execute(
            f"INSERT INTO {table} "
            f"({id_column}, schema_version, version, content_sha256, payload, created_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)",
            (identifier, schema_version, version, digest, payload),
        )
        self._connection.commit()
        return record

    def get(self, record_type: type[T], identifier: str, version: int = 1) -> T:
        if record_type not in self._TABLES:
            raise TypeError(f"unsupported product record: {record_type.__name__}")
        table, id_column = self._TABLES[record_type]
        cursor = self._connection.cursor()
        cursor.execute(
            f"SELECT payload FROM {table} WHERE {id_column} = %s AND version = %s",
            (identifier, version),
        )
        row = cursor.fetchone()
        if row is None:
            raise RepositoryNotFoundError((record_type.__name__, identifier, version))
        payload = row[0]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        return TypeAdapter(record_type).validate_python(payload)

    def list_versions(self, record_type: type[T], identifier: str) -> tuple[T, ...]:
        if record_type not in self._TABLES:
            raise TypeError(f"unsupported product record: {record_type.__name__}")
        table, id_column = self._TABLES[record_type]
        cursor = self._connection.cursor()
        cursor.execute(
            f"SELECT payload FROM {table} WHERE {id_column} = %s ORDER BY version",
            (identifier,),
        )
        records: list[T] = []
        for row in cursor.fetchall():
            payload = row[0]
            if isinstance(payload, str):
                import json

                payload = json.loads(payload)
            records.append(TypeAdapter(record_type).validate_python(payload))
        return tuple(records)

    def list_workspaces(self, *, latest_only: bool = True) -> tuple[DomainWorkspace, ...]:
        """List workspaces using deterministic database ordering."""

        cursor = self._connection.cursor()
        if latest_only:
            cursor.execute(
                "SELECT payload FROM product_workspaces AS workspace "
                "WHERE workspace.version = (SELECT MAX(latest.version) "
                "FROM product_workspaces AS latest "
                "WHERE latest.workspace_id = workspace.workspace_id) "
                "ORDER BY workspace.workspace_id, workspace.version"
            )
        else:
            cursor.execute(
                "SELECT payload FROM product_workspaces "
                "ORDER BY workspace_id, version"
            )
        records: list[DomainWorkspace] = []
        for row in cursor.fetchall():
            payload = row[0]
            if isinstance(payload, str):
                import json

                payload = json.loads(payload)
            records.append(TypeAdapter(DomainWorkspace).validate_python(payload))
        return tuple(records)

    def latest_workspace(self, workspace_id: str) -> DomainWorkspace:
        """Return one latest workspace through the same public contract."""

        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM product_workspaces AS workspace "
            "WHERE workspace.workspace_id = %s "
            "AND workspace.version = (SELECT MAX(latest.version) "
            "FROM product_workspaces AS latest WHERE latest.workspace_id = %s)",
            (workspace_id, workspace_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise RepositoryNotFoundError((DomainWorkspace.__name__, workspace_id))
        payload = row[0]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        return TypeAdapter(DomainWorkspace).validate_python(payload)
