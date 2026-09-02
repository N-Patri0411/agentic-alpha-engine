"""Development-only Alpha Vantage daily OHLCV source adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ..evidence import EvidenceObservation, MarketBar, SourceDocument
from ..evidence.contracts import ExtractionProvenance
from ..settings import required_setting
from .base import AdapterHealth
from .rate_limit import RequestPacer

_DAILY_FUNCTION = "TIME_SERIES_DAILY"
_DAILY_SERIES_KEY = "Time Series (Daily)"
_API_URL = "https://www.alphavantage.co/query"


class AlphaVantageDailyAdapter:
    """Collect daily OHLCV data without claiming point-in-time completeness."""

    name = "alpha_vantage_daily"
    requires_api_key = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        min_interval_seconds: float = 12.0,
        now: Callable[[], datetime] | None = None,
        pacer: RequestPacer | None = None,
    ) -> None:
        self._api_key = api_key or required_setting("ALPHAVANTAGE_API_KEY")
        self._client = client or httpx.Client(timeout=20.0)
        self._now = now or (lambda: datetime.now(UTC))
        self._pacer = pacer or RequestPacer(min_interval_seconds)

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter=self.name, implemented=True, requires_api_key=True)

    def collect(self, query: dict[str, object]) -> list[EvidenceObservation]:
        issuer_entity_id = str(query["issuer_entity_id"])
        symbol = str(query["symbol"]).upper()
        if not issuer_entity_id or not symbol:
            raise ValueError("issuer_entity_id and symbol are required")
        outputsize = str(query.get("outputsize", "compact"))
        if outputsize not in {"compact", "full"}:
            raise ValueError("outputsize must be compact or full")
        self._pacer.wait()
        params = {
            "function": _DAILY_FUNCTION,
            "symbol": symbol,
            "outputsize": outputsize,
            "apikey": self._api_key,
        }
        response = self._client.get(_API_URL, params=params)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self._raise_provider_error(payload)
        series = payload.get(_DAILY_SERIES_KEY)
        if not isinstance(series, dict) or not series:
            raise ValueError("Alpha Vantage response did not contain daily OHLCV data")
        retrieved_at = self._now()
        content_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        safe_parameters = {
            "function": _DAILY_FUNCTION,
            "symbol": symbol,
            "outputsize": outputsize,
        }
        safe_url = f"{_API_URL}?{urlencode(safe_parameters)}"
        observations = [
            self._observation(
                issuer_entity_id=issuer_entity_id,
                symbol=symbol,
                date_text=date_text,
                values=values,
                content_sha256=content_sha256,
                source_url=safe_url,
                retrieved_at=retrieved_at,
                run_id=str(query.get("run_id", "alpha-vantage-daily")),
            )
            for date_text, values in sorted(series.items())
        ]
        return observations

    @staticmethod
    def _raise_provider_error(payload: dict[str, Any]) -> None:
        for key in ("Error Message", "Note", "Information"):
            detail = payload.get(key)
            if isinstance(detail, str) and detail:
                raise RuntimeError(f"Alpha Vantage {key.lower()}: {detail}")

    def _observation(
        self,
        *,
        issuer_entity_id: str,
        symbol: str,
        date_text: str,
        values: object,
        content_sha256: str,
        source_url: str,
        retrieved_at: datetime,
        run_id: str,
    ) -> EvidenceObservation:
        if not isinstance(values, dict):
            raise ValueError(f"Alpha Vantage daily data for {date_text} must be an object")
        try:
            trading_date = datetime.fromisoformat(date_text).date()
            open_price = float(values["1. open"])
            high = float(values["2. high"])
            low = float(values["3. low"])
            close = float(values["4. close"])
            volume = int(values["5. volume"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid Alpha Vantage OHLCV bar for {date_text}") from error
        bar_start = datetime.combine(trading_date, time.min, tzinfo=UTC)
        bar_end = bar_start + timedelta(days=1)
        # This free provider does not offer a historical availability guarantee.
        # The response becomes available to this system only at retrieval time.
        document = SourceDocument(
            source_kind="market_data",
            source_tier="market_data",
            source_adapter=self.name,
            source_url=source_url,
            content_sha256=content_sha256,
            issuer_entity_id=issuer_entity_id,
            observed_at=bar_end,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            usage_note=(
                "Alpha Vantage daily OHLCV; development-only and not certified as "
                "point-in-time historical market data"
            ),
            external_id=f"{symbol}:{date_text}",
            title=f"{symbol} daily OHLCV {date_text}",
        )
        return EvidenceObservation(
            idempotency_key=f"{self.name}:{symbol}:{date_text}:{content_sha256}",
            document=document,
            mentioned_entity_ids=(issuer_entity_id,),
            payload=MarketBar(
                symbol=symbol,
                bar_start=bar_start,
                bar_end=bar_end,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
            ),
            extraction=ExtractionProvenance(
                extractor_name=self.name,
                extractor_version="1",
                run_id=run_id,
            ),
        )
