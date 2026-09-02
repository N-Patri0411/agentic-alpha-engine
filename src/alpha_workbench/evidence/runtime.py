"""Bounded event intake and nightly living-graph consolidation services."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ..adapters.base import ObservationAdapter
from ..graph_registry import GraphSnapshot
from .contracts import EvidenceRunReceipt
from .ledger import DuckDBEvidenceLedger

if TYPE_CHECKING:
    from ..agents.graph_adjudicator import GraphAdjudicationReport, GraphAdjudicatorAgent


class EvidenceIntakeService:
    """Runs one allow-listed adapter and records an append-only collection receipt."""

    def __init__(
        self, ledger: DuckDBEvidenceLedger, adapters: Mapping[str, ObservationAdapter]
    ) -> None:
        self._ledger = ledger
        self._adapters = dict(adapters)

    def collect(
        self, *, adapter_name: str, query: dict[str, object], run_id: str
    ) -> EvidenceRunReceipt:
        """Collect a bounded event input without allowing adapter selection by an LLM."""

        adapter = self._adapters.get(adapter_name)
        if adapter is None:
            raise ValueError(f"adapter is not registered for evidence intake: {adapter_name}")
        started_at = datetime.now(UTC)
        try:
            observations = adapter.collect(query)
            self._ledger.append_many(observations)
        except Exception as error:
            receipt = self._receipt(
                adapter_name=adapter_name,
                run_id=run_id,
                started_at=started_at,
                status="failed",
                errors=(f"{type(error).__name__}: {error}",),
            )
            self._ledger.append_run_receipt(receipt)
            return receipt
        receipt = self._receipt(
            adapter_name=adapter_name,
            run_id=run_id,
            started_at=started_at,
            status="completed",
            observation_idempotency_keys=tuple(
                observation.idempotency_key for observation in observations
            ),
        )
        self._ledger.append_run_receipt(receipt)
        return receipt

    def record_failure(
        self, *, adapter_name: str, run_id: str, error: Exception
    ) -> EvidenceRunReceipt:
        """Record a bounded pre-collection failure, such as document discovery."""

        started_at = datetime.now(UTC)
        receipt = self._receipt(
            adapter_name=adapter_name,
            run_id=run_id,
            started_at=started_at,
            status="failed",
            errors=(f"{type(error).__name__}: {error}",),
        )
        self._ledger.append_run_receipt(receipt)
        return receipt

    @staticmethod
    def _receipt(
        *,
        adapter_name: str,
        run_id: str,
        started_at: datetime,
        status: Literal["completed", "failed"],
        observation_idempotency_keys: tuple[str, ...] = (),
        errors: tuple[str, ...] = (),
    ) -> EvidenceRunReceipt:
        material = ":".join((run_id, adapter_name, status, *observation_idempotency_keys, *errors))
        return EvidenceRunReceipt(
            idempotency_key="intake-receipt:" + hashlib.sha256(material.encode()).hexdigest(),
            run_id=run_id,
            adapter_name=adapter_name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            observation_idempotency_keys=observation_idempotency_keys,
            errors=errors,
        )


class NightlyGraphConsolidator:
    """Publishes one immutable as-of snapshot from ledger evidence."""

    def __init__(self, ledger: DuckDBEvidenceLedger, adjudicator: GraphAdjudicatorAgent) -> None:
        self._ledger = ledger
        self._adjudicator = adjudicator

    def consolidate(
        self,
        *,
        current_snapshot: GraphSnapshot,
        as_of_time: datetime,
        next_snapshot_id: str,
        snapshot_path: Path,
    ) -> GraphAdjudicationReport:
        observations = self._ledger.observations_as_of(as_of_time)
        return self._adjudicator.adjudicate_and_publish(
            observations=observations,
            current_snapshot=current_snapshot,
            as_of_time=as_of_time,
            next_snapshot_id=next_snapshot_id,
            snapshot_path=snapshot_path,
        )
