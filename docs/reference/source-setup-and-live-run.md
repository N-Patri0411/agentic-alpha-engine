# Source setup and first live evidence run

The source adapters are intentionally deterministic collectors. They fetch,
time-stamp, hash, and store source material. Luna is used only after collection
by the Extraction Agent to propose a typed relationship from retained text; it
does not scrape the web itself.

## Local credentials

Keep credentials only in the ignored repository-root `.env` file. The file is
excluded by `.gitignore`; `.env.example` is safe to commit because it holds
names only. Never paste a key into a terminal command, Git commit, issue, or
chat message.

```dotenv
# Already configured for this project.
OPENAI_API_KEY=
SEC_USER_AGENT=AgenticAlphaWorkbench your-contact-email@example.com

# Needed to enable the remaining two live adapters.
ALPHAVANTAGE_API_KEY=
TAVILY_API_KEY=
```

There is no SEC key. Keep the user agent descriptive and use the project contact
email. The collector runs far below the SEC's published 10-requests-per-second
guideline.

### Alpha Vantage market data

1. Open [Alpha Vantage support](https://www.alphavantage.co/support/#api-key).
2. Request a free key with a real email address.
3. Copy it into `ALPHAVANTAGE_API_KEY` in the root `.env` file.

The initial adapter requests only daily OHLCV bars for the six tradeable
semiconductor entities. It is marked development-only because this free source
does not guarantee historical point-in-time availability, so it must not support
an alpha-performance claim.

### Tavily web discovery

1. Create an account at the [Tavily platform](https://app.tavily.com).
2. Copy a dashboard key into `TAVILY_API_KEY` in the root `.env` file.

The current Tavily free tier is documented as 1,000 credits per month. The
adapter submits eight focused discovery queries per whole-source run, returns at
most five results per query, and labels every result `discovery`. Discovery can
surface candidates and contradictions but can never publish a graph edge on its
own.

## What the command collects

After adding both keys, run this from the repository root:

```powershell
.venv\Scripts\python.exe -m alpha_workbench collect-initial-sources --preview-limit 32
```

It creates or updates the ignored local ledger at
`data/private/evidence.duckdb`, then prints safe JSON previews. A normal initial
run attempts the following bounded collection:

| Source family | Initial scope | What is retained |
| --- | --- | --- |
| SEC EDGAR | NVDA, AMD, TSM: newest selected filing | One ranked filing passage, URL, accession, source hash, dates |
| SEC earnings fallback | newest EX-99 exhibit from eligible 8-K/6-K | One official earnings-text window when an exhibit exists |
| Official IR/newsrooms | 8 registry entities | Landing page plus at most two same-site newsroom links each |
| Web discovery | 8 registry entities | Up to five Tavily result summaries per focused query |
| Market data | NVDA, AMD, TSM, MU, GFS, UMC | Daily OHLCV observations from Alpha Vantage |

Every source call returns a receipt with `completed` or `failed`. A failure is
visible in output and the append-only ledger; it is not turned into fabricated
evidence. Official newsroom pages that do not expose a trustworthy publication
date use their retrieval time and are unsuitable for historical as-of claims.

## What we will inspect together

The live demonstration will show a short, redacted preview for each source:

- SEC: filing title, official URL, filing availability time, selected passage.
- Earnings: official release/exhibit URL, publication time, retained text window.
- Newsroom: configured official page or linked release, source hash, relationship-focused excerpt.
- Web: title, URL, date, discovery summary and its lower-tier label.
- Market: symbol, date range, OHLCV values, and development-only label.

Then we can feed selected text observations—not prices—into the Luna-powered
Extraction Agent. Any relationship it proposes remains a draft and must pass
evidence validation and Graph Adjudication before a new immutable graph snapshot
can be published.
