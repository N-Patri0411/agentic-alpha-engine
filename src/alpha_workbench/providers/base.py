"""Shared local request pacing and safe result helpers."""

from __future__ import annotations

import os
import time
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from .contracts import CapabilityName, CoverageReport, ProviderBudget, ProviderProvenance


class LocalRequestBudget:
    def __init__(self, budget: ProviderBudget) -> None:
        self.budget = budget
        self._calls = 0
        self._minute_calls: deque[float] = deque()

    def acquire(self, estimated_cost: Decimal = Decimal("0")) -> None:
        now = time.monotonic()
        while self._minute_calls and now - self._minute_calls[0] >= 60:
            self._minute_calls.popleft()
        if (
            self.budget.max_requests_per_run is not None
            and self._calls >= self.budget.max_requests_per_run
        ):
            raise RuntimeError("provider local per-run request budget exhausted")
        if (
            self.budget.max_requests_per_minute is not None
            and len(self._minute_calls) >= self.budget.max_requests_per_minute
        ):
            raise RuntimeError("provider local per-minute request budget exhausted")
        if (
            self.budget.max_estimated_cost is not None
            and estimated_cost * (self._calls + 1) > self.budget.max_estimated_cost
        ):
            raise RuntimeError("provider local estimated-cost budget exhausted")
        self._calls += 1
        self._minute_calls.append(now)


def credential_from_env(config: dict[str, Any], default_env: str) -> str | None:
    """Resolve only an environment variable name from configuration, never a secret value."""

    env_name = config.get("credentials_env", default_env)
    if not isinstance(env_name, str) or not env_name:
        raise ValueError("credentials_env must name an environment variable")
    return os.environ.get(env_name)


def post_json(
    client: httpx.Client,
    url: str,
    payload: object,
    *,
    budget: LocalRequestBudget,
    headers: dict[str, str] | None = None,
) -> Any:
    budget.acquire()
    try:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        raise RuntimeError(
            f"provider request failed{f' with HTTP {status}' if status else ''}"
        ) from None


def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str],
    budget: LocalRequestBudget,
    estimated_cost: Decimal = Decimal("0"),
) -> Any:
    budget.acquire(estimated_cost)
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        raise RuntimeError(
            f"provider request failed{f' with HTTP {status}' if status else ''}"
        ) from None


def provenance(
    provider_id: str,
    *,
    source_url: str | None = None,
    content_sha256: str | None = None,
    license_note: str = "",
) -> ProviderProvenance:
    return ProviderProvenance(
        provider_id=provider_id,
        request_id=str(uuid4()),
        retrieved_at=datetime.now(UTC),
        source_url=source_url,
        content_sha256=content_sha256,
        license_note=license_note,
    )


def unsupported(
    capability: CapabilityName,
    provider_id: str,
    *,
    requested_count: int = 0,
    detail: str = "",
    as_of_time: datetime | None = None,
) -> tuple[CoverageReport, ProviderProvenance]:
    return (
        CoverageReport(
            capability=capability,
            status="unsupported",
            requested_count=requested_count,
            returned_count=0,
            detail=detail or "provider does not implement this capability",
        ),
        provenance(provider_id),
    )
