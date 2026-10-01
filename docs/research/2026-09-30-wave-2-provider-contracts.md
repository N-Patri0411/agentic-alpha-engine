# Wave 2 provider contracts

## Scope

The alpha_workbench.providers package defines a common interface for instrument
discovery, identifier mapping, daily/weekly/monthly history, fundamentals,
corporate actions, exchange calendars, FX, and evidence documents. Every call
returns a typed result with an explicit CoverageReport, request as_of_time, and
provider provenance. Unimplemented capability methods return unsupported;
providers do not imply complete coverage when an endpoint or data category is
absent.

Requests enforce timezone-aware cutoffs and valid date ranges. Results reject
items whose available_at is later than as_of_time. Providers with no certified
historical publication chronology use retrieval time as the conservative
availability time. They can serve current workflows after the selection
cutoff is set, but their capability reports do not claim point-in-time support.

## Adapters

- OpenFIGI maps third-party identifiers through /v3/mapping. Ticker requests
  require an exchange value; multiple candidate listings remain explicitly
  ambiguous instead of selecting an arbitrary FIGI. API key use is optional
  and configured through OPENFIGI_API_KEY.
- EODHD provides exchange-agnostic name/symbol search, historical EOD bars,
  fundamentals snapshots, splits/dividends, and FX bars. It reports calendar
  and evidence-document coverage as unsupported. EODHD authentication uses
  EODHD_API_KEY; its documented token query parameter is confined to the
  outbound request and omitted from provenance, result serialization, and
  sanitized HTTP errors.
- alpha_vantage_compat adapts the existing AlphaVantageDailyAdapter into the
  new historical-bars contract. It keeps its development-only and
  non-point-in-time boundary and uses ALPHAVANTAGE_API_KEY.

All adapters expose local request-per-minute and request-per-run budgets.
EODHD also tracks an optional caller-configured estimated request cost; this is
a guardrail estimate, not a vendor billing calculation. Adapter configs store
environment variable names only. Tests use committed JSON fixtures through
HTTP mock transports, never external calls or API keys.

## Vendor references and limits

Endpoint shapes follow the vendors' current public documentation:
[EODHD historical data](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes),
[EODHD API overview](https://eodhd.com/financial-apis/quick-start-with-your-financial-data-apis),
and [OpenFIGI mapping API](https://www.openfigi.com/api/documentation).
Vendor plan entitlements, rate limits, licensing, and endpoint schemas can
change. Live vendor calls were not run for this implementation. EODHD's
fundamentals endpoint is treated as a current snapshot; it is not presented as
as-filed point-in-time data. Exchange calendar and evidence-document adapters
remain explicit follow-up capabilities.
