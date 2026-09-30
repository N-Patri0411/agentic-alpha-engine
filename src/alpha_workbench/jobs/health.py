"""Dependency health and readiness primitives for API and worker entrypoints."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DependencyHealth:
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def probe(name: str, check: Callable[[], object]) -> DependencyHealth:
    """Run a safe dependency probe without exposing exception details."""

    try:
        result = check()
    except Exception as error:  # noqa: BLE001 - health must never crash the process
        return DependencyHealth(name=name, ok=False, detail=type(error).__name__)
    if result is False:
        return DependencyHealth(name=name, ok=False, detail="probe returned false")
    return DependencyHealth(name=name, ok=True, detail="ready")


def readiness(checks: Iterable[DependencyHealth]) -> tuple[bool, list[DependencyHealth]]:
    values = list(checks)
    return all(check.ok for check in values), values
