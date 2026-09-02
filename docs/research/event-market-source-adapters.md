# Event and market source adapters

This slice adds three common-observation inputs. None can create or publish a
graph edge. They only preserve source evidence for later Extraction and Graph
Adjudicator stages.

- `OfficialEarningsEvidenceAdapter` accepts configured official transcripts,
  webcast pages, investor-relations releases, and SEC 8-K exhibits. It records
  the source class rather than pretending each item has the same reliability.
  Audio-only webcasts are not transcribed by this adapter; a source needs an
  official text page or transcript before it becomes text evidence.
- `WebDiscoveryAdapter` normalizes results from an injected search provider (or
  supplied results). It is deliberately discovery-tier evidence and has no
  graph publishing API.
- `AlphaVantageDailyAdapter` fetches daily OHLCV through `ALPHAVANTAGE_API_KEY`.
  It records retrieval time as availability because this free endpoint is not a
  certified point-in-time historical source. It is therefore development-only
  and unsuitable for claims about historical alpha.

All adapters use local, credential-free fixtures in normal tests. A live Alpha
Vantage collection is only possible after adding `ALPHAVANTAGE_API_KEY` to the
ignored root `.env` file. The initial provider-neutral discovery implementation
is `TavilyDiscoverySearchBackend`, enabled by local `TAVILY_API_KEY`; it uses
the REST endpoint directly rather than placing a vendor SDK inside an agent.

See [source setup and first live run](../reference/source-setup-and-live-run.md)
for the current bounded whole-source command and its retained outputs.
