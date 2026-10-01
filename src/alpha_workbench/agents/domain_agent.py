"""Domain description interpreter used before instrument discovery."""

from __future__ import annotations

from datetime import datetime

from alpha_workbench.domain import DomainSpec, parse_domain_spec
from alpha_workbench.product.contracts import SelectionMode


class DomainAgent:
    """Deterministic baseline; an injected language model may replace interpretation."""

    def interpret(
        self,
        description: str,
        *,
        regions: tuple[str, ...] = ("global",),
        cadence: str = "daily",
        base_currency: str = "USD",
        selection_mode: SelectionMode = "current",
        selection_time: datetime,
        target_count: int = 10,
    ) -> DomainSpec:
        return parse_domain_spec(
            description,
            regions=regions,
            cadence=cadence,  # type: ignore[arg-type]
            base_currency=base_currency,
            selection_mode=selection_mode,
            selection_time=selection_time,
            target_count=target_count,
        )
