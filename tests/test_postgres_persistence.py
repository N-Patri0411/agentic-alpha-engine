from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_workbench.persistence import PostgresProductRepository
from alpha_workbench.product import DomainWorkspace, InstrumentRef, UniverseSpec


class _RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executions.append((query, params))

    def fetchone(self) -> None:
        return None


class _RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = _RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_product_migration_is_idempotent_and_isolated() -> None:
    migrations = Path(__file__).parents[1] / "infra" / "migrations"
    migration = migrations / "001_product_foundation.sql"
    text = migration.read_text(encoding="utf-8")
    assert text.count("CREATE TABLE IF NOT EXISTS product_") == 7
    assert "product_workspaces" in text
    assert "product_readiness_reports" in text
    assert "product_job" not in text
    assert "CREATE TABLE IF NOT EXISTS jobs" not in text
    assert "CREATE TABLE IF NOT EXISTS evidence" not in text
    assert "CREATE TABLE IF NOT EXISTS graph" not in text
    assert "CREATE OR REPLACE FUNCTION" in text

    jobs_text = (migrations / "002_jobs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS jobs" in jobs_text
    assert "CREATE TABLE IF NOT EXISTS job_events" in jobs_text
    assert "product_" not in jobs_text


def test_postgres_universe_insert_uses_universe_id_as_repository_key() -> None:
    connection = _RecordingConnection()
    repository = PostgresProductRepository(connection)
    universe = UniverseSpec(
        universe_id="u-key",
        workspace_id="w-owner",
        domain="semiconductors",
        instruments=(
            InstrumentRef(
                instrument_id="FIGI:AMD",
                symbol="AMD",
                exchange="XNAS",
                currency="USD",
            ),
        ),
        selection_time=datetime(2024, 1, 1, tzinfo=UTC),
        selection_mode="current",
        selection_method="fixture",
    )

    repository.put(universe)

    assert connection.recording_cursor.executions[0][1] == ("u-key", 1)
    assert connection.recording_cursor.executions[1][1][0] == "u-key"
    assert "product_universe_versions" in connection.recording_cursor.executions[1][0]


def test_postgres_domain_lock_uses_one_transaction_for_both_records() -> None:
    connection = _RecordingConnection()
    repository = PostgresProductRepository(connection)
    workspace = DomainWorkspace(
        workspace_id="w-lock",
        name="Lock test",
        domain="semiconductors",
        universe_id="u-lock",
    )
    universe = UniverseSpec(
        universe_id="u-lock",
        workspace_id="w-lock",
        domain="semiconductors",
        instruments=(
            InstrumentRef(
                instrument_id="FIGI:AMD", symbol="AMD", exchange="XNAS", currency="USD"
            ),
        ),
        selection_time=datetime(2024, 1, 1, tzinfo=UTC),
        selection_mode="current",
        selection_method="fixture",
    )

    repository.put_workspace_with_universe(workspace, universe)

    assert len(connection.recording_cursor.executions) == 4
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_DSN"), reason="set TEST_POSTGRES_DSN for integration"
)
def test_postgres_repository_round_trip() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["TEST_POSTGRES_DSN"]
    with psycopg.connect(dsn) as connection:
        repository = PostgresProductRepository(connection)
        workspace = DomainWorkspace(
            workspace_id="test-wave1",
            name="Integration",
            domain="semiconductors",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        repository.put(workspace)
        assert (
            repository.get(DomainWorkspace, "test-wave1").content_sha256()
            == workspace.content_sha256()
        )
        assert len(repository.list_versions(DomainWorkspace, "test-wave1")) == 1
