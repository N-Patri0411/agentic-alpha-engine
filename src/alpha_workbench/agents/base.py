"""Small base class for observable standalone agent callables."""

from __future__ import annotations

from time import perf_counter

from .contracts import AgentRequest, AgentResult


class SkeletonAgent:
    """A safe placeholder until a role receives its own implementation slice."""

    name: str

    def run(self, request: AgentRequest) -> AgentResult:
        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        started = perf_counter()
        return AgentResult(
            run_id=request.run_id,
            agent=self.name,
            status="completed",
            message=f"{self.name} skeleton completed without side effects",
            latency_ms=int((perf_counter() - started) * 1000),
        )
