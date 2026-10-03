"""Append-only feature artifact repositories for offline and PostgreSQL runtimes."""

from __future__ import annotations

import json
from typing import Any, Protocol, TypeVar, cast

from pydantic import TypeAdapter

from alpha_workbench.product.canonical import canonical_json

from .contracts import (
    FeatureDefinition,
    FeatureFrameManifest,
    FeatureObservation,
    FeatureSetVersion,
)

FeatureRecord = TypeVar(
    "FeatureRecord", FeatureDefinition, FeatureSetVersion, FeatureObservation, FeatureFrameManifest
)


class ImmutableFeatureRecordError(ValueError):
    """Raised if an existing feature artifact key is reused with new content."""


class FeatureRepository(Protocol):
    def put_definition(self, definition: FeatureDefinition) -> FeatureDefinition: ...

    def put_feature_set(self, feature_set: FeatureSetVersion) -> FeatureSetVersion: ...

    def put_observation(self, observation: FeatureObservation) -> FeatureObservation: ...

    def put_manifest(self, manifest: FeatureFrameManifest) -> FeatureFrameManifest: ...

    def get_definition(self, feature_id: str, version: int = 1) -> FeatureDefinition: ...

    def get_feature_set(self, feature_set_id: str, version: int = 1) -> FeatureSetVersion: ...

    def get_observation(self, observation_id: str) -> FeatureObservation: ...

    def get_manifest(self, manifest_id: str) -> FeatureFrameManifest: ...

    def list_definitions(self) -> tuple[FeatureDefinition, ...]: ...


class InMemoryFeatureRepository:
    """Test/development repository with append-only version keys."""

    def __init__(self) -> None:
        self._records: dict[tuple[type[Any], str, int], Any] = {}

    def _put(self, record: FeatureRecord, identifier: str) -> FeatureRecord:
        key = (type(record), identifier, record.version)
        prior = self._records.get(key)
        if prior is not None:
            if prior.content_sha256() != record.content_sha256():
                raise ImmutableFeatureRecordError(
                    f"{type(record).__name__} {identifier} is immutable"
                )
            return cast(FeatureRecord, prior)
        self._records[key] = record
        return record

    def put_definition(self, definition: FeatureDefinition) -> FeatureDefinition:
        return self._put(definition, definition.feature_id)

    def put_feature_set(self, feature_set: FeatureSetVersion) -> FeatureSetVersion:
        return self._put(feature_set, feature_set.feature_set_id)

    def put_observation(self, observation: FeatureObservation) -> FeatureObservation:
        return self._put(observation, observation.observation_id)

    def put_manifest(self, manifest: FeatureFrameManifest) -> FeatureFrameManifest:
        return self._put(manifest, manifest.manifest_id)

    def _get(
        self, record_type: type[FeatureRecord], identifier: str, version: int
    ) -> FeatureRecord:
        try:
            return cast(FeatureRecord, self._records[(record_type, identifier, version)])
        except KeyError as error:
            raise KeyError((record_type.__name__, identifier, version)) from error

    def get_definition(self, feature_id: str, version: int = 1) -> FeatureDefinition:
        return self._get(FeatureDefinition, feature_id, version)

    def get_feature_set(self, feature_set_id: str, version: int = 1) -> FeatureSetVersion:
        return self._get(FeatureSetVersion, feature_set_id, version)

    def get_observation(self, observation_id: str) -> FeatureObservation:
        return self._get(FeatureObservation, observation_id, 1)

    def get_manifest(self, manifest_id: str) -> FeatureFrameManifest:
        return self._get(FeatureFrameManifest, manifest_id, 1)

    def list_definitions(self) -> tuple[FeatureDefinition, ...]:
        items = [item for (kind, _, _), item in self._records.items() if kind is FeatureDefinition]
        return tuple(sorted(items, key=lambda item: (item.feature_id, item.version)))


class PostgresFeatureRepository:
    """Small DB-API repository using the append-only ``feature_artifacts`` table."""

    _TABLE = "feature_artifacts"

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def _put(self, record: FeatureRecord, kind: str, identifier: str) -> FeatureRecord:
        digest, payload = record.content_sha256(), canonical_json(record)
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                "SELECT content_sha256 FROM feature_artifacts "
                "WHERE artifact_kind = %s AND artifact_id = %s AND version = %s",
                (kind, identifier, record.version),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if str(prior[0]) != digest:
                    raise ImmutableFeatureRecordError(f"{kind} {identifier} is immutable")
                return record
            cursor.execute(
                "INSERT INTO feature_artifacts "
                "(artifact_kind, artifact_id, version, content_sha256, payload) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (kind, identifier, record.version, digest, payload),
            )
            self._connection.commit()
            return record
        except Exception:
            rollback = getattr(self._connection, "rollback", None)
            if callable(rollback):
                rollback()
            raise

    def _get(
        self, model: type[FeatureRecord], kind: str, identifier: str, version: int
    ) -> FeatureRecord:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM feature_artifacts "
            "WHERE artifact_kind = %s AND artifact_id = %s AND version = %s",
            (kind, identifier, version),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError((kind, identifier, version))
        payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        return TypeAdapter(model).validate_python(payload)

    def put_definition(self, definition: FeatureDefinition) -> FeatureDefinition:
        return self._put(definition, "definition", definition.feature_id)

    def put_feature_set(self, feature_set: FeatureSetVersion) -> FeatureSetVersion:
        return self._put(feature_set, "feature_set", feature_set.feature_set_id)

    def put_observation(self, observation: FeatureObservation) -> FeatureObservation:
        return self._put(observation, "observation", observation.observation_id)

    def put_manifest(self, manifest: FeatureFrameManifest) -> FeatureFrameManifest:
        return self._put(manifest, "manifest", manifest.manifest_id)

    def get_definition(self, feature_id: str, version: int = 1) -> FeatureDefinition:
        return self._get(FeatureDefinition, "definition", feature_id, version)

    def get_feature_set(self, feature_set_id: str, version: int = 1) -> FeatureSetVersion:
        return self._get(FeatureSetVersion, "feature_set", feature_set_id, version)

    def get_observation(self, observation_id: str) -> FeatureObservation:
        return self._get(FeatureObservation, "observation", observation_id, 1)

    def get_manifest(self, manifest_id: str) -> FeatureFrameManifest:
        return self._get(FeatureFrameManifest, "manifest", manifest_id, 1)

    def list_definitions(self) -> tuple[FeatureDefinition, ...]:
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT payload FROM feature_artifacts WHERE artifact_kind = %s "
            "ORDER BY artifact_id, version",
            ("definition",),
        )
        results = []
        for (payload,) in cursor.fetchall():
            if isinstance(payload, str):
                payload = json.loads(payload)
            results.append(TypeAdapter(FeatureDefinition).validate_python(payload))
        return tuple(results)
