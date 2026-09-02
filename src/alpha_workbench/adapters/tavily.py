"""Tavily-backed implementation of the provider-neutral discovery protocol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from ..settings import required_setting
from .web_discovery import DiscoveryResult


class TavilyDiscoverySearchBackend:
    """Search adapter used only by ``WebDiscoveryAdapter`` as discovery evidence."""

    name = "tavily"
    _URL = "https://api.tavily.com/search"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        max_results: int = 5,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if max_results < 1 or max_results > 10:
            raise ValueError("max_results must be between 1 and 10")
        self._api_key = api_key or required_setting("TAVILY_API_KEY")
        self._client = client or httpx.Client(timeout=20.0)
        self._max_results = max_results
        self._now = now or (lambda: datetime.now(UTC))

    def search(self, query: str) -> list[DiscoveryResult]:
        response = self._client.post(
            self._URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "query": query,
                "max_results": self._max_results,
                "search_depth": "basic",
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("Tavily response did not contain a results list")
        retrieved_at = self._now()
        results: list[DiscoveryResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            raw_url = item.get("url")
            raw_title = item.get("title")
            raw_content = item.get("content")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (raw_url, raw_title, raw_content)
            ):
                continue
            url = str(raw_url)
            title = str(raw_title)
            content = str(raw_content)
            results.append(
                DiscoveryResult.model_validate(
                    {
                        "source_url": url,
                        "title": title,
                        "summary": content,
                        "published_at": self._published_at(
                            item.get("published_date"), retrieved_at
                        ),
                    }
                )
            )
        return results

    @staticmethod
    def _published_at(value: object, fallback: datetime) -> datetime:
        if not isinstance(value, str) or not value:
            return fallback
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
