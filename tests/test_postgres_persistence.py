from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_workbench.persistence import PostgresProductRepository
from alpha_workbench.product import DomainWorkspace


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
