"""Explicit per-workspace readiness and source pins for catalog features."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field, model_validator

from alpha_workbench.product.contracts import ContractBase


class WorkspaceFeatureBinding(ContractBase):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1)
    feature_id: str = Field(min_length=1)
    feature_version: int = Field(ge=1)
    status: Literal["ready", "unavailable"] = "unavailable"
    reason: str = ""
    observation_count: int = Field(default=0, ge=0)
    dataset_version_id: str | None = None
    graph_snapshot_id: str | None = None
    graph_snapshot_digest: str | None = None
    available_at: datetime | None = None
    source_artifact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def provenance_is_complete(self) -> WorkspaceFeatureBinding:
        if bool(self.graph_snapshot_id) != bool(self.graph_snapshot_digest):
            raise ValueError("graph snapshot ID and digest must be pinned together")
        if self.status == "ready":
            if self.observation_count == 0 or self.available_at is None:
                raise ValueError("ready binding requires observations and available_at")
            if self.dataset_version_id is None and self.graph_snapshot_id is None:
                raise ValueError("ready binding requires a dataset or graph snapshot pin")
        return self

    def ready_for(self, *, as_of_time: datetime, graph_snapshot_id: str | None) -> bool:
        return (
            self.status == "ready"
            and self.observation_count > 0
            and self.available_at is not None
            and self.available_at <= as_of_time
            and (self.graph_snapshot_id is None or self.graph_snapshot_id == graph_snapshot_id)
        )


class WorkspaceFeatureBindingRepository(Protocol):
    def list_bindings(self, workspace_id: str) -> tuple[WorkspaceFeatureBinding, ...]: ...

    def put_binding(self, binding: WorkspaceFeatureBinding) -> WorkspaceFeatureBinding: ...


class InMemoryWorkspaceFeatureBindingRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, int], WorkspaceFeatureBinding] = {}

    def list_bindings(self, workspace_id: str) -> tuple[WorkspaceFeatureBinding, ...]:
        return tuple(
            sorted(
                (item for (wid, _, _), item in self._items.items() if wid == workspace_id),
                key=lambda item: (item.feature_id, item.version),
            )
        )

    def put_binding(self, binding: WorkspaceFeatureBinding) -> WorkspaceFeatureBinding:
        key = (binding.workspace_id, binding.feature_id, binding.version)
        previous = self._items.get(key)
        if previous is not None and previous.content_sha256() != binding.content_sha256():
            raise ValueError("workspace feature binding version is immutable")
        self._items[key] = previous or binding
        return self._items[key]


class PostgresWorkspaceFeatureBindingRepository:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def list_bindings(self, workspace_id: str) -> tuple[WorkspaceFeatureBinding, ...]:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM workspace_feature_bindings WHERE workspace_id = %s "
            "ORDER BY feature_id, version",
            (workspace_id,),
        )
        output = []
        for (payload,) in cursor.fetchall():
            if isinstance(payload, str):
                payload = json.loads(payload)
            output.append(WorkspaceFeatureBinding.model_validate(payload))
        return tuple(output)

    def put_binding(self, binding: WorkspaceFeatureBinding) -> WorkspaceFeatureBinding:
        cursor = self._connection.cursor()
        digest, payload = binding.content_sha256(), binding.canonical_json()
        try:
            cursor.execute(
                "SELECT content_sha256 FROM workspace_feature_bindings WHERE workspace_id = %s "
                "AND feature_id = %s AND version = %s",
                (binding.workspace_id, binding.feature_id, binding.version),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if str(prior[0]) != digest:
                    raise ValueError("workspace feature binding version is immutable")
                return binding
            cursor.execute(
                "INSERT INTO workspace_feature_bindings "
                "(workspace_id, feature_id, feature_version, version, content_sha256, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                (
                    binding.workspace_id,
                    binding.feature_id,
                    binding.feature_version,
                    binding.version,
                    digest,
                    payload,
                ),
            )
            self._connection.commit()
            return binding
        except Exception:
            self._connection.rollback()
            raise
