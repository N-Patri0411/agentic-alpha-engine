"""Append-only DuckDB persistence for source evidence and collection receipts."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .contracts import EvidenceObservation, EvidenceRunReceipt, SourceCatalogEntry


class DuckDBEvidenceLedger:
    """Local durable store with idempotent inserts and no update/delete API."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(str(path))
        self._connection.execute(
            """
            create table if not exists evidence_observations (
                observation_id varchar primary key,
                idempotency_key varchar unique not null,
                issuer_entity_id varchar not null,
                source_kind varchar not null,
                source_tier varchar not null,
                source_url varchar not null,
                content_sha256 varchar not null,
                observed_at timestamp with time zone not null,
                available_at timestamp with time zone not null,
                retrieved_at timestamp with time zone not null,
                payload_type varchar not null,
                record json not null
            )
            """
        )
        self._connection.execute(
            """
            create table if not exists evidence_source_catalog (
                entry_id varchar primary key,
                idempotency_key varchar unique not null,
                issuer_entity_id varchar not null,
                source_kind varchar not null,
                source_url varchar not null,
                registered_at timestamp with time zone not null,
                record json not null
            )
            """
        )
        self._connection.execute(
            """
            create table if not exists evidence_run_receipts (
                receipt_id varchar primary key,
                idempotency_key varchar unique not null,
                run_id varchar not null,
                adapter_name varchar not null,
                status varchar not null,
                started_at timestamp with time zone not null,
                finished_at timestamp with time zone not null,
                record json not null
            )
            """
        )

    def append(self, observation: EvidenceObservation) -> bool:
        """Persist an observation once. Duplicate idempotency keys are harmless."""

        if self._exists("evidence_observations", observation.idempotency_key):
            return False
        document = observation.document
        self._connection.execute(
            """
            insert into evidence_observations values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(observation.observation_id),
                observation.idempotency_key,
                document.issuer_entity_id,
                document.source_kind,
                document.source_tier,
                document.source_url,
                document.content_sha256,
                document.observed_at,
                document.available_at,
                document.retrieved_at,
                observation.payload.payload_type,
                json.dumps(observation.model_dump(mode="json"), sort_keys=True),
            ],
        )
        return True

    def append_many(self, observations: list[EvidenceObservation]) -> int:
        """Append a batch, returning the count of first-time records."""

        return sum(self.append(observation) for observation in observations)

    def register_source(self, entry: SourceCatalogEntry) -> bool:
        if self._exists("evidence_source_catalog", entry.idempotency_key):
            return False
        self._connection.execute(
            "insert into evidence_source_catalog values (?, ?, ?, ?, ?, ?, ?)",
            [
                str(entry.entry_id),
                entry.idempotency_key,
                entry.issuer_entity_id,
                entry.source_kind,
                entry.source_url,
                entry.registered_at,
                json.dumps(entry.model_dump(mode="json"), sort_keys=True),
            ],
        )
        return True

    def append_run_receipt(self, receipt: EvidenceRunReceipt) -> bool:
        if self._exists("evidence_run_receipts", receipt.idempotency_key):
            return False
        self._connection.execute(
            "insert into evidence_run_receipts values (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                str(receipt.receipt_id),
                receipt.idempotency_key,
                receipt.run_id,
                receipt.adapter_name,
                receipt.status,
                receipt.started_at,
                receipt.finished_at,
                json.dumps(receipt.model_dump(mode="json"), sort_keys=True),
            ],
        )
        return True

    def observations_as_of(self, as_of_time: object) -> list[EvidenceObservation]:
        """Return only evidence that was available by an explicit research time."""

        rows = self._connection.execute(
            """
            select record from evidence_observations
            where available_at <= ?
            order by available_at, observation_id
            """,
            [as_of_time],
        ).fetchall()
        return [EvidenceObservation.model_validate_json(record) for (record,) in rows]

    def observations_for_run(
        self, run_id: str, *, source_adapter: str | None = None
    ) -> list[EvidenceObservation]:
        """Return immutable observations emitted by one source-collection run."""

        query = """
            select record from evidence_observations
            where json_extract_string(record, '$.extraction.run_id') = ?
        """
        parameters: list[object] = [run_id]
        if source_adapter is not None:
            query += " and json_extract_string(record, '$.document.source_adapter') = ?"
            parameters.append(source_adapter)
        query += " order by available_at, observation_id"
        rows = self._connection.execute(query, parameters).fetchall()
        return [EvidenceObservation.model_validate_json(record) for (record,) in rows]

    def count_observations(self) -> int:
        row = self._connection.execute("select count(*) from evidence_observations").fetchone()
        assert row is not None
        return int(row[0])

    def close(self) -> None:
        self._connection.close()

    def _exists(self, table: str, idempotency_key: str) -> bool:
        result = self._connection.execute(
            f"select 1 from {table} where idempotency_key = ?", [idempotency_key]
        ).fetchone()
        return result is not None

    def __enter__(self) -> DuckDBEvidenceLedger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
