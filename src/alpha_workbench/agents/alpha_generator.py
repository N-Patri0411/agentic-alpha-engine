"""Bounded alpha candidate generation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from ..alpha import AlphaCandidate, AlphaGenerationResult, CandidateProvenance, FeatureCatalog
from ..alpha.dsl import DSLValidationError, Expression, parse_expression
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

    def generate(self, request: AgentRequest) -> AlphaGenerationResult:
        if not request.payload.get("features") and not request.payload.get("feature_catalog"):
            result = AlphaGenerationResult(candidates=[])
            self.last_result = result
            return result
        catalog = self._catalog(request.payload)
        catalog.validate_point_in_time()
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
        for index, value in enumerate(values[: limit * 2]):
            try:
                candidate = self._candidate(value, index, catalog, fingerprint)
                if candidate.id in seen or candidate.expression in {c.expression for c in accepted}:
                    raise ValueError("duplicate candidate")
                candidate.validate_expression(catalog.names)
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
        features = [{"name": item} if isinstance(item, str) else item for item in raw]
        return FeatureCatalog(features=features, as_of_time=payload.get("as_of_time"))  # type: ignore[arg-type]

    @staticmethod
    def _candidate(
        value: Any, index: int, catalog: FeatureCatalog, fingerprint: str
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
        return AlphaCandidate(
            id=identifier, expression=expression, rationale=rationale, provenance=provenance
        )


def _features(node: Expression, names: set[str]) -> set[str]:
    result = {node.name} if node.name in names else set()
    for arg in node.args:
        if isinstance(arg, Expression):
            result.update(_features(arg, names))
    return result
