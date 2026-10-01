"""Provider-neutral orchestration for universe selection."""

from __future__ import annotations

from alpha_workbench.domain import DomainCandidate, DomainPlan, DomainPlanner, DomainSpec


class UniverseAgent:
    """Applies the deterministic selection policy to resolved provider candidates."""

    def __init__(self, planner: DomainPlanner | None = None) -> None:
        self._planner = planner or DomainPlanner()

    def recommend(
        self,
        domain_spec: DomainSpec,
        candidates: tuple[DomainCandidate, ...],
        *,
        provider_coverage: dict[str, float] | None = None,
    ) -> DomainPlan:
        return self._planner.plan(
            domain_spec,
            candidates,
            provider_coverage=provider_coverage,
        )
