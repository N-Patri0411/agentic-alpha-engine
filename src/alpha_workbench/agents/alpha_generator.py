"""Bounded alpha candidate generation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from ..alpha import (
    AlphaCandidate,
    AlphaGenerationResult,
    CandidateProvenance,
    FeatureCatalog,
    FeatureReference,
    GeneratorFeatureRef,
    SignalSpec,
)
from ..alpha.dsl import (
    DSLValidationError,
    Expression,
    canonicalize_expression,
    parse_expression,
    validate_typed_expression,
)
from ..llm.models import FakeLLMClient, LLMClient
from .base import SkeletonAgent
from .contracts import AgentRequest, AgentResult


class AlphaGeneratorAgent(SkeletonAgent):
    name = "alpha_generator"

    def __init__(self, llm: LLMClient | None = None, *, max_candidates: int = 10) -> None:
        if max_candidates < 1 or max_candidates > 50:
            raise ValueError("max_candidates must be between 1 and 50")
        self.llm = llm or FakeLLMClient()
        self.max_candidates = max_candidates
        self.last_result: AlphaGenerationResult | None = None
        self.trial_ledger = InMemoryTrialLedger()

    @property
    def service(self) -> AlphaGeneratorService:
        """Narrow service facade suitable for a REST adapter."""
        return AlphaGeneratorService(self, self.trial_ledger)

    def generate(self, request: AgentRequest) -> AlphaGenerationResult:
        if not request.payload.get("features") and not request.payload.get("feature_catalog"):
            result = AlphaGenerationResult(candidates=[])
            self.last_result = result
            return result
        catalog = self._catalog(request.payload)
        catalog.validate_point_in_time()
        frequency = catalog.validate_frequency(
            str(request.payload.get("frequency", catalog.frequency)),
            str(request.payload.get("feature_frequency_policy", catalog.feature_frequency_policy)),
        )
        requested_limit = request.payload.get("max_candidates", self.max_candidates)
        if not isinstance(requested_limit, int):
            raise ValueError("max_candidates must be an integer")
        limit = min(self.max_candidates, requested_limit)
        if limit < 1:
            raise ValueError("max_candidates must be positive")
        user = json.dumps(
            {
                "features": [f.model_dump(mode="json") for f in catalog.features],
                "context": request.payload.get("context", ""),
                "max_candidates": limit,
                "frequency": frequency,
                "dsl": (
                    "Rank, ZScore, Delay, Delta, Mean, StdDev, Correlation, Add, Sub, "
                    "Mul, Div, Neg, Clip"
                ),
            },
            sort_keys=True,
            default=str,
        )
        raw = self.llm.complete_json(
            system=(
                "Propose paper-research hypotheses only; never give trading advice. Return exactly "
                "a JSON object shaped as {candidates:[{id,expression,rationale}]}. Every field is "
                "a string. expression must use only supplied feature names and these functions: "
                "Rank, ZScore, Delay, Delta, Mean, StdDev, Correlation, Add, Sub, "
                "Mul, Div, Neg, Clip. "
                'Example: {"candidates":[{"id":"c1","expression":"Rank(momentum)",'
                '"rationale":"cross-sectional ranking"}]}. '
            ),
            user=user
            + "\nReturn no markdown and include id, expression, and rationale for every candidate.",
        )
        values = raw.get("candidates", [raw] if "expression" in raw else [])
        if not isinstance(values, list):
            raise ValueError("model candidates must be a JSON array")
        fingerprint = hashlib.sha256(user.encode("utf-8")).hexdigest()
        accepted: list[AlphaCandidate] = []
        rejected: list[str] = []
        seen: set[str] = set()
        if len(values) > min(100, limit * 2):
            rejected.append(f"candidate batch exceeds bounded limit of {min(100, limit * 2)}")
        for index, value in enumerate(values[: min(100, limit * 2)]):
            try:
                candidate = self._candidate(value, index, catalog, fingerprint, request.payload)
                canonical = candidate.canonical_expression
                if candidate.id in seen or canonical in {c.canonical_expression for c in accepted}:
                    raise ValueError("duplicate candidate")
                candidate.validate_expression(catalog.names)
                assert candidate.signal is not None
                validate_typed_expression(
                    parse_expression(candidate.signal.canonical_expression, catalog.names),
                    supported_axes={item.name: item.supported_axes for item in catalog.features},
                    frequency=frequency,
                )
                seen.add(candidate.id)
                accepted.append(candidate)
                if len(accepted) >= limit:
                    break
            except (TypeError, ValueError, DSLValidationError, KeyError) as error:
                keys = sorted(value.keys()) if isinstance(value, dict) else []
                rejected.append(f"candidate {index} (keys={keys}): {error}")
        result = AlphaGenerationResult(
            candidates=accepted, rejected=rejected, as_of_time=catalog.as_of_time
        )
        self.last_result = result
        return result

    def run(self, request: AgentRequest) -> AgentResult:
        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        started = datetime.now(UTC)
        try:
            result = self.generate(request)
            status: Literal["completed", "failed"] = "completed"
            message = json.dumps(
                {
                    "candidates": [c.model_dump(mode="json") for c in result.candidates],
                    "rejected": result.rejected,
                },
                default=str,
            )
        except (TypeError, ValueError, DSLValidationError) as error:
            status, message = "failed", str(error)
        elapsed = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return AgentResult(
            run_id=request.run_id,
            agent=self.name,
            status=status,
            message=message,
            latency_ms=max(0, elapsed),
        )

    @staticmethod
    def _catalog(payload: dict[str, object]) -> FeatureCatalog:
        raw = payload.get("features", payload.get("feature_catalog", []))
        if isinstance(raw, dict):
            raw = raw.get("features", [])
        if not isinstance(raw, list) or not raw:
            raise ValueError("payload must provide a non-empty features list")
        features = [
            GeneratorFeatureRef.model_validate({"name": item} if isinstance(item, str) else item)
            for item in raw
        ]
        return FeatureCatalog(
            features=features,
            as_of_time=payload.get("as_of_time"),  # type: ignore[arg-type]
            frequency=payload.get("frequency", "daily"),  # type: ignore[arg-type]
            feature_frequency_policy=payload.get("feature_frequency_policy", "strict"),  # type: ignore[arg-type]
            graph_version_id=payload.get("graph_version_id"),  # type: ignore[arg-type]
        )

    @staticmethod
    def _candidate(
        value: Any,
        index: int,
        catalog: FeatureCatalog,
        fingerprint: str,
        payload: dict[str, object],
    ) -> AlphaCandidate:
        if not isinstance(value, dict):
            raise TypeError("candidate must be an object")
        if isinstance(value.get("candidate"), dict):
            value = value["candidate"]
        # A few providers use these unambiguous aliases despite the schema.
        expression = value.get("expression", value.get("formula"))
        rationale = value.get("rationale", value.get("reason"))
        if not isinstance(expression, str) or not isinstance(rationale, str):
            raise ValueError("expression and rationale are required strings")
        parsed = parse_expression(expression, catalog.names)
        canonical = canonicalize_expression(expression, catalog.names)
        used = sorted(_features(parsed, catalog.names))
        sources = sorted(
            {
                sid
                for feature in catalog.features
                if feature.name in used
                for sid in feature.source_artifact_ids
            }
        )
        provenance = CandidateProvenance(
            generated_by="alpha_generator",
            feature_names=used,
            source_artifact_ids=sources,
            generated_at=datetime.now(UTC),
            request_fingerprint=fingerprint,
        )
        identifier = value.get("id", f"candidate-{index + 1}")
        if not isinstance(identifier, str):
            raise ValueError("id must be a string")
        referenced = tuple(
            FeatureReference(
                name=feature.name,
                value_type=feature.value_type,
                frequency=feature.frequency,
                feature_version_id=feature.feature_version_id,
                dataset_version_id=feature.dataset_version_id,
                graph_version_id=feature.graph_version_id,
                source_artifact_ids=tuple(feature.source_artifact_ids),
            )
            for feature in catalog.features
            if feature.name in used
        )
        graph_pins = {
            reference.graph_version_id for reference in referenced if reference.graph_version_id
        }
        if len(graph_pins) > 1 or (
            catalog.graph_version_id is not None
            and any(pin != catalog.graph_version_id for pin in graph_pins)
        ):
            raise ValueError("referenced graph features have incompatible graph version pins")
        signal = SignalSpec(
            expression=expression,
            canonical_expression=canonical,
            frequency=catalog.frequency,
            feature_frequency_policy=catalog.feature_frequency_policy,
            feature_refs=referenced,
            as_of_time=catalog.as_of_time,
            rationale=rationale,
            provenance=provenance,
            graph_version_id=catalog.graph_version_id or next(iter(graph_pins), None),
            portfolio_config=_mapping_config(payload, "portfolio_config"),
            risk_config=_mapping_config(payload, "risk_config"),
            validation_config=_mapping_config(payload, "validation_config"),
        )
        return AlphaCandidate(
            id=identifier,
            expression=canonical,
            rationale=rationale,
            provenance=provenance,
            signal=signal,
        )


def _features(node: Expression, names: set[str]) -> set[str]:
    result = {node.name} if node.name in names else set()
    for arg in node.args:
        if isinstance(arg, Expression):
            result.update(_features(arg, names))
    return result


class TrialLedger(Protocol):
    """Persistence seam for experiment-wide dedupe and trial accounting."""

    def record(self, experiment_id: str, formula: str, limit: int) -> int: ...

    def count(self, experiment_id: str) -> int: ...


class InMemoryTrialLedger:
    """Deterministic process-local ledger; inject durable storage in production."""

    def __init__(self) -> None:
        self._trials: dict[str, list[str]] = {}

    def record(self, experiment_id: str, formula: str, limit: int) -> int:
        formulas = self._trials.setdefault(experiment_id, [])
        if formula in formulas:
            return len(formulas)
        if len(formulas) >= limit:
            raise ValueError("experiment trial limit exceeded")
        formulas.append(formula)
        return len(formulas)

    def count(self, experiment_id: str) -> int:
        return len(self._trials.get(experiment_id, ()))


class PostgresTrialLedger:
    """Durable, cross-process experiment dedupe and trial accounting."""

    def __init__(self, connection_factory: Any) -> None:
        self._connection_factory = connection_factory

    def record(self, experiment_id: str, formula: str, limit: int) -> int:
        with self._connection_factory() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (experiment_id,))
                cursor.execute(
                    "SELECT trial_count FROM experiment_trial_counters "
                    "WHERE experiment_id = %s FOR UPDATE",
                    (experiment_id,),
                )
                row = cursor.fetchone()
                count = int(row[0]) if row else 0
                cursor.execute(
                    "SELECT 1 FROM experiment_trials "
                    "WHERE experiment_id = %s AND canonical_formula = %s",
                    (experiment_id, formula),
                )
                if cursor.fetchone() is not None:
                    connection.commit()
                    return count
                if count >= limit:
                    raise ValueError("experiment trial limit exceeded")
                cursor.execute(
                    "INSERT INTO experiment_trials "
                    "(experiment_id, canonical_formula) VALUES (%s, %s)",
                    (experiment_id, formula),
                )
                cursor.execute(
                    "INSERT INTO experiment_trial_counters "
                    "(experiment_id, trial_count) VALUES (%s, 1) "
                    "ON CONFLICT (experiment_id) DO UPDATE SET trial_count = "
                    "experiment_trial_counters.trial_count + 1 "
                    "RETURNING trial_count",
                    (experiment_id,),
                )
                count = int(cursor.fetchone()[0])
                connection.commit()
                return count
            except Exception:
                connection.rollback()
                raise

    def count(self, experiment_id: str) -> int:
        with self._connection_factory() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT trial_count FROM experiment_trial_counters WHERE experiment_id = %s",
                (experiment_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0


class AlphaGeneratorService:
    """Small service API that routers can call without AgentRequest internals."""

    def __init__(self, agent: AlphaGeneratorAgent, ledger: TrialLedger | None = None) -> None:
        self.agent = agent
        self.ledger = ledger or InMemoryTrialLedger()

    def generate(
        self,
        payload: dict[str, object],
        *,
        run_id: str = "alpha-service",
        experiment_id: str | None = None,
        trial_limit: int = 100,
    ) -> AlphaGenerationResult:
        if not 1 <= trial_limit <= 100_000:
            raise ValueError("trial_limit must be between 1 and 100000")
        if experiment_id is not None:
            current_trials = self.ledger.count(experiment_id)
            if current_trials >= trial_limit:
                return AlphaGenerationResult(
                    candidates=[],
                    rejected=["experiment trial limit exceeded before model generation"],
                    experiment_id=experiment_id,
                    trial_count=current_trials,
                    trial_limit=trial_limit,
                )
        result = self.agent.generate(
            AgentRequest(run_id=run_id, agent="alpha_generator", payload=payload)
        )
        if experiment_id is not None:
            recorded: list[AlphaCandidate] = []
            rejected = list(result.rejected)
            trial_count = self.ledger.count(experiment_id)
            for candidate in result.candidates:
                try:
                    trial_count = self.ledger.record(
                        experiment_id, candidate.canonical_expression, trial_limit
                    )
                    recorded.append(candidate)
                except ValueError as error:
                    rejected.append(f"candidate {candidate.id}: {error}")
            result = AlphaGenerationResult(
                candidates=recorded,
                rejected=rejected[:100],
                as_of_time=result.as_of_time,
                experiment_id=experiment_id,
                trial_count=trial_count,
                trial_limit=trial_limit,
            )
        return result


def _mapping_config(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a string-keyed object")
    return value
