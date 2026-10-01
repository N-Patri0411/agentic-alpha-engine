"""EODHD REST adapter with conservative retrieval-time availability."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from .base import LocalRequestBudget, credential_from_env, get_json, provenance, unsupported
from .contracts import (
    CorporateAction,
    CorporateActionsResult,
    CoverageReport,
    CoverageStatus,
    DataChronology,
    DiscoveryResult,
    EvidenceDocumentRequest,
    EvidenceDocumentsResult,
    ExchangeCalendarRequest,
    ExchangeCalendarResult,
    FundamentalRecord,
    FundamentalsResult,
    FxRate,
    FxRatesRequest,
    FxRatesResult,
    HistoricalBar,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    IdentifierMappingRequest,
    InstrumentQuery,
    InstrumentRecord,
    MappingResult,
    ProviderBudget,
    ProviderCapability,
)

_BASE_URL = "https://eodhd.com/api"


class EodhdAdapter:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        base_url: str = _BASE_URL,
        max_requests_per_minute: int = 60,
        max_requests_per_run: int = 1000,
        estimated_cost_per_request: Decimal = Decimal("0"),
        max_estimated_cost: Decimal | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("EODHD_API_KEY is required")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)
        self._base_url = base_url.rstrip("/")
        self._budget = ProviderBudget(
            max_requests_per_minute=max_requests_per_minute,
            max_requests_per_run=max_requests_per_run,
            max_estimated_cost=max_estimated_cost,
        )
        self._estimated_cost = estimated_cost_per_request
        self._limiter = LocalRequestBudget(self._budget)
        self._capability = ProviderCapability(
            provider_id="eodhd",
            display_name="EODHD",
            capabilities=(
                "instrument_discovery",
                "historical_bars",
                "fundamentals",
                "corporate_actions",
                "fx_rates",
            ),
            markets=("global_equities", "forex"),
            frequencies=("daily", "weekly", "monthly"),
            supports_point_in_time=False,
            rate_limit_per_minute=max_requests_per_minute,
            estimated_cost_per_request=estimated_cost_per_request,
            licensing_note="Availability uses retrieval time; review plan terms.",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> EodhdAdapter:
        budget = config.get("budget", {})
        if not isinstance(budget, dict):
            raise ValueError("EODHD budget must be a mapping")
        cost = Decimal(str(config.get("estimated_cost_per_request", "0")))
        max_cost_raw = budget.get("max_estimated_cost")
        return cls(
            api_key=credential_from_env(config, "EODHD_API_KEY"),
            base_url=str(config.get("base_url", _BASE_URL)),
            max_requests_per_minute=int(budget.get("max_requests_per_minute", 60)),
            max_requests_per_run=int(budget.get("max_requests_per_run", 1000)),
            estimated_cost_per_request=cost,
            max_estimated_cost=Decimal(str(max_cost_raw)) if max_cost_raw is not None else None,
        )

    @property
    def capability(self) -> ProviderCapability:
        return self._capability

    @property
    def budget(self) -> ProviderBudget:
        return self._budget

    def discover_instruments(self, request: InstrumentQuery) -> DiscoveryResult:
        path = f"search/{quote(request.query, safe='')}"
        params: dict[str, str] = {"limit": "100", "type": "all"}
        if request.exchange:
            params["exchange"] = request.exchange
        rows = self._get(path, params)
        if not isinstance(rows, list):
            raise ValueError("EODHD search response must be an array")
        items = tuple(
            InstrumentRecord(
                symbol=str(row.get("Code", "")),
                exchange=str(row.get("Exchange", "")),
                name=str(row.get("Name", "")),
                currency=_optional_str(row.get("Currency")),
                country=_optional_str(row.get("Country")),
                asset_class=_optional_str(row.get("Type")),
                isin=_optional_str(row.get("ISIN")),
                provider_symbol=(
                    f"{row.get('Code', '')}.{row.get('Exchange', '')}"
                    if row.get("Code") and row.get("Exchange")
                    else None
                ),
            )
            for row in rows
            if isinstance(row, dict) and row.get("Code") and row.get("Exchange")
        )
        available = self._now()
        items = tuple(item for item in items if request.as_of_time >= available)
        status: CoverageStatus = "complete" if items else "missing"
        return DiscoveryResult(
            items=items,
            coverage=CoverageReport(
                capability="instrument_discovery",
                status=status,
                requested_count=1,
                returned_count=1 if items else 0,
                missing_identifiers=() if items else (request.query,),
                detail="" if items else "no matching listing available by as_of_time",
            ),
            provenance=provenance("eodhd", source_url=f"{self._base_url}/{path}"),
            as_of_time=request.as_of_time,
        )

    def map_identifier(self, request: IdentifierMappingRequest) -> MappingResult:
        report, source = unsupported("identifier_mapping", "eodhd", requested_count=1)
        return MappingResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult:
        symbol = _provider_symbol(request.instrument)
        path = f"eod/{quote(symbol, safe='')}"
        period = {"daily": "d", "weekly": "w", "monthly": "m"}[request.interval]
        rows = self._get(
            path,
            {
                "from": request.start.isoformat(),
                "to": request.end.isoformat(),
                "period": period,
                "order": "a",
                "fmt": "json",
            },
        )
        if not isinstance(rows, list):
            raise ValueError("EODHD historical bars response must be an array")
        retrieved_at = self._now()
        output: list[HistoricalBar] = []
        missing: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            bar_date = date.fromisoformat(str(row["date"]))
            start = datetime.combine(bar_date, time.min, tzinfo=UTC)
            end = start + timedelta(days=1)
            if retrieved_at > request.as_of_time:
                missing.append(bar_date.isoformat())
                continue
            output.append(
                HistoricalBar(
                    instrument=request.instrument,
                    start=start,
                    end=end,
                    open=_decimal(row["open"]),
                    high=_decimal(row["high"]),
                    low=_decimal(row["low"]),
                    close=_decimal(row["close"]),
                    volume=_decimal(row["volume"]),
                    adjusted_close=_decimal(row["adjusted_close"])
                    if row.get("adjusted_close") is not None
                    else None,
                    chronology=DataChronology(
                        observed_at=end,
                        available_at=retrieved_at,
                        as_of_time=request.as_of_time,
                    ),
                )
            )
        status = _coverage_status(len(output), len(rows), bool(missing))
        return HistoricalBarsResult(
            items=tuple(output),
            coverage=CoverageReport(
                capability="historical_bars",
                status=status,
                requested_count=len(rows),
                returned_count=len(output),
                missing_identifiers=tuple(missing),
                detail=(
                    "EODHD does not certify publication times; availability uses retrieval time"
                ),
            ),
            provenance=provenance("eodhd", source_url=f"{self._base_url}/{path}"),
            as_of_time=request.as_of_time,
        )

    def fundamentals(self, request: InstrumentQuery) -> FundamentalsResult:
        if not request.exchange:
            return FundamentalsResult(
                items=(),
                coverage=CoverageReport(
                    capability="fundamentals",
                    status="missing",
                    requested_count=1,
                    missing_identifiers=(request.query,),
                    detail="fundamentals require symbol and exchange",
                ),
                provenance=provenance("eodhd"),
                as_of_time=request.as_of_time,
            )
        symbol = f"{request.query}.{request.exchange}"
        path = f"fundamentals/{quote(symbol, safe='')}"
        payload = self._get(path)
        if not isinstance(payload, dict):
            raise ValueError("EODHD fundamentals response must be an object")
        retrieved_at = self._now()
        instrument = InstrumentRecord(symbol=request.query, exchange=request.exchange)
        records = []
        for key, value in _flatten(payload):
            if retrieved_at <= request.as_of_time:
                records.append(
                    FundamentalRecord(
                        instrument=instrument,
                        metric=key,
                        value=_fundamental_value(value),
                        chronology=DataChronology(
                            observed_at=retrieved_at,
                            available_at=retrieved_at,
                            as_of_time=request.as_of_time,
                        ),
                    )
                )
        available = bool(records)
        return FundamentalsResult(
            items=tuple(records),
            coverage=CoverageReport(
                capability="fundamentals",
                status="complete" if available else "missing",
                requested_count=1,
                returned_count=1 if available else 0,
                missing_identifiers=() if available else (symbol,),
                detail="Current snapshot; historical as-filed availability is not guaranteed.",
            ),
            provenance=provenance("eodhd", source_url=f"{self._base_url}/{path}"),
            as_of_time=request.as_of_time,
        )

    def corporate_actions(self, request: HistoricalBarsRequest) -> CorporateActionsResult:
        symbol = _provider_symbol(request.instrument)
        path = f"splits-dividends/{quote(symbol, safe='')}"
        payload = self._get(
            path, {"from": request.start.isoformat(), "to": request.end.isoformat()}
        )
        if not isinstance(payload, dict):
            raise ValueError("EODHD corporate actions response must be an object")
        retrieved_at = self._now()
        actions: list[CorporateAction] = []
        for row in _dict_rows(payload.get("Splits")):
            ex_date = date.fromisoformat(str(row.get("date")))
            if retrieved_at <= request.as_of_time:
                actions.append(
                    CorporateAction(
                        instrument=request.instrument,
                        action_type="split",
                        ex_date=ex_date,
                        ratio=_decimal(row.get("split", 0)),
                        chronology=DataChronology(
                            observed_at=datetime.combine(ex_date, time.min, tzinfo=UTC),
                            available_at=retrieved_at,
                            as_of_time=request.as_of_time,
                        ),
                    )
                )
        for row in _dict_rows(payload.get("Dividends")):
            ex_date = date.fromisoformat(str(row.get("date")))
            if retrieved_at <= request.as_of_time:
                pay_date = (
                    date.fromisoformat(str(row["paymentDate"])) if row.get("paymentDate") else None
                )
                actions.append(
                    CorporateAction(
                        instrument=request.instrument,
                        action_type="dividend",
                        ex_date=ex_date,
                        amount=_decimal(row.get("value", 0)),
                        currency=_optional_str(row.get("currency")),
                        payment_date=pay_date,
                        chronology=DataChronology(
                            observed_at=datetime.combine(ex_date, time.min, tzinfo=UTC),
                            available_at=retrieved_at,
                            as_of_time=request.as_of_time,
                        ),
                    )
                )
        return CorporateActionsResult(
            items=tuple(actions),
            coverage=CoverageReport(
                capability="corporate_actions",
                status="complete" if retrieved_at <= request.as_of_time else "missing",
                requested_count=1,
                returned_count=1 if retrieved_at <= request.as_of_time else 0,
                missing_identifiers=() if retrieved_at <= request.as_of_time else (symbol,),
                detail="availability is conservatively set to retrieval time",
            ),
            provenance=provenance("eodhd", source_url=f"{self._base_url}/{path}"),
            as_of_time=request.as_of_time,
        )

    def exchange_calendar(self, request: ExchangeCalendarRequest) -> ExchangeCalendarResult:
        report, source = unsupported("exchange_calendars", "eodhd", requested_count=1)
        return ExchangeCalendarResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def fx_rates(self, request: FxRatesRequest) -> FxRatesResult:
        pair = request.base_currency.upper() + request.quote_currency.upper() + ".FOREX"
        path = f"eod/{quote(pair, safe='')}"
        rows = self._get(
            path,
            {
                "from": request.start.isoformat(),
                "to": request.end.isoformat(),
                "period": "d",
                "order": "a",
                "fmt": "json",
            },
        )
        if not isinstance(rows, list):
            raise ValueError("EODHD FX response must be an array")
        retrieved_at = self._now()
        items = tuple(
            FxRate(
                base_currency=request.base_currency.upper(),
                quote_currency=request.quote_currency.upper(),
                rate=_decimal(row["close"]),
                observed_at=datetime.combine(
                    date.fromisoformat(str(row["date"])), time.min, tzinfo=UTC
                ),
                available_at=retrieved_at,
                as_of_time=request.as_of_time,
            )
            for row in rows
            if isinstance(row, dict) and retrieved_at <= request.as_of_time
        )
        return FxRatesResult(
            items=items,
            coverage=CoverageReport(
                capability="fx_rates",
                status="complete" if items else "missing",
                requested_count=len(rows),
                returned_count=len(items),
                missing_identifiers=() if items else (pair,),
                detail="availability is conservatively set to retrieval time",
            ),
            provenance=provenance("eodhd", source_url=f"{self._base_url}/{path}"),
            as_of_time=request.as_of_time,
        )

    def evidence_documents(self, request: EvidenceDocumentRequest) -> EvidenceDocumentsResult:
        report, source = unsupported("evidence_documents", "eodhd", requested_count=1)
        return EvidenceDocumentsResult(
            items=(), coverage=report, provenance=source, as_of_time=request.as_of_time
        )

    def _get(self, endpoint: str, params: dict[str, str] | None = None) -> Any:
        query = dict(params or {})
        query["api_token"] = self._api_key
        query.setdefault("fmt", "json")
        return get_json(
            self._client,
            f"{self._base_url}/{endpoint}",
            params=query,
            budget=self._limiter,
            estimated_cost=self._estimated_cost,
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)


def _provider_symbol(instrument: InstrumentRecord) -> str:
    return instrument.provider_symbol or f"{instrument.symbol}.{instrument.exchange}"


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None and value != "" else None


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid decimal value {value!r}") from error


def _coverage_status(returned: int, requested: int, forced_partial: bool) -> CoverageStatus:
    if returned == 0:
        return "missing"
    if forced_partial or returned < requested:
        return "partial"
    return "complete"


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _flatten(value: object, prefix: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        result: list[tuple[str, object]] = []
        for key, child in value.items():
            result.extend(_flatten(child, f"{prefix}.{key}" if prefix else str(key)))
        return result
    if isinstance(value, list):
        result = []
        for index, child in enumerate(value):
            result.extend(_flatten(child, f"{prefix}[{index}]"))
        return result
    return [(prefix, value)] if prefix else []


def _fundamental_value(value: object) -> str | int | float | Decimal | None:
    if value is None or isinstance(value, (str, int, float)):
        return value
    return str(value)
