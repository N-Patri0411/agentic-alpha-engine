# Agentic Alpha Search System — Complete Project Knowledge Base

> Everything discussed across the full planning session, in one document.
> Theory, architecture, tooling, implementation strategy, and the GNN build plan.
> Last updated: 2026

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Core Finance Concepts](#2-core-finance-concepts)
   - 2.1 Sharpe Ratio
   - 2.2 Alpha
   - 2.3 Beta
   - 2.4 How They Connect
   - 2.5 CAPM and Market-Neutral Investing
   - 2.6 Information Coefficient (IC)
   - 2.7 Alpha Decay
3. [System Architecture](#3-system-architecture)
   - 3.1 Pipeline Overview
   - 3.2 Agent Roles
   - 3.3 Data Flow
4. [Comparison with Existing Systems](#4-comparison-with-existing-systems)
   - 4.1 Alpha-GPT
   - 4.2 Multi-Modal Multi-Agent Research (ACL 2025)
   - 4.3 MarketSenseAI 2.0
   - 4.4 Where Your Approach Stands
5. [Tooling and Dev Stack](#5-tooling-and-dev-stack)
   - 5.1 Current Stack Assessment
   - 5.2 Missing Tools
   - 5.3 Revised Recommended Stack
6. [Data Strategy](#6-data-strategy)
   - 6.1 The Decay Problem with Standard News
   - 6.2 Slow-Decaying Data Sources
   - 6.3 Tier Rankings for a Solo Developer
7. [GNN Module — Semiconductor Supply Chain](#7-gnn-module--semiconductor-supply-chain)
   - 7.1 Why GNN and Why Semiconductors First
   - 7.2 Five-Step Build Strategy
   - 7.3 Architecture Decisions
   - 7.4 Project File Structure
   - 7.5 Success Criteria
8. [Known Gaps and Critical Risks](#8-known-gaps-and-critical-risks)
9. [Theory Learning Roadmap](#9-theory-learning-roadmap)
10. [Interview Preparation — Key Q&A](#10-interview-preparation--key-qa)
11. [Build Sequence](#11-build-sequence)

---

## 1. Project Overview

### What You Are Building

An autonomous multi-agent system that continuously discovers, tests, and deploys quantitative alpha factors for systematic equity trading. The system is designed to replace the manual process of alpha research — where quant researchers spend months hand-crafting trading signals — with an automated pipeline that generates, backtests, and retires signals without human intervention in the loop.

### The Core Problem

Every profitable trading signal (alpha factor) eventually stops working. Competitors discover it, trade it, and arbitrage the edge away. This is called **alpha decay**. The only sustainable response is to replace decaying signals with new ones faster than they expire. Human researchers cannot do this at scale. An automated multi-agent system can.

### The Value Proposition

- **Breadth over depth**: Generate thousands of candidate signals and keep the ones with genuine predictive power
- **Continuous operation**: The system runs overnight, refreshing the signal library before markets open
- **Adaptive retirement**: Signals are automatically decommissioned when their IC (Information Coefficient) falls below the viability threshold
- **Novel data sources**: The system targets data that is slow to decay — earnings call audio, regulatory filing language drift, supply chain graph signals — rather than commoditised news sentiment

### Project Stage

Research and prototype. Not connected to live trading. The immediate goal is a working system that can demonstrate genuine alpha discovery on historical data with credible backtest methodology.

---

## 2. Core Finance Concepts

### 2.1 Sharpe Ratio

**The question it answers**: Was the risk worth the return?

Two portfolios can return 20% in the same year and have completely different quality of returns. One achieved it with smooth, consistent monthly gains. The other with violent swings that happened to average out. The Sharpe Ratio distinguishes them.

**The formula:**
```
Sharpe Ratio = (Portfolio Return − Risk-Free Rate) ÷ Standard Deviation of Returns
```

- **Portfolio Return**: What you actually made
- **Risk-Free Rate**: What you'd have made in a US Treasury bond (~4–5% currently). You subtract this because that return is free — you should only earn credit for the *extra* risk you took
- **Standard Deviation of Returns**: How much your returns bounced around. High = rollercoaster. Low = smooth

**Interpreting the number:**

| Sharpe Ratio | Interpretation |
|---|---|
| Below 1.0 | Most professionals consider this not worth the risk |
| 1.0 – 2.0 | Good, respectable |
| Above 2.0 | Excellent, rare in practice |
| Above 3.0 | Either exceptional or the backtest has a bug |

**Why it matters for your system**: Sharpe is the primary fitness function in your Gatekeeper agent. A formula that returns 40% with violent swings loses to one returning 25% smoothly. The scoring rubric is risk-adjusted return, not raw return.

**The backtest gap**: A Sharpe of 2.0 in backtest translating to 1.0–1.2 in live trading is considered a success. If someone claims live performance equals backtest performance exactly, be skeptical. Backtests don't account for transaction costs, slippage, or the fact that other traders partially arbitrage the signal before execution.

---

### 2.2 Alpha

**The question it answers**: How much of your return came from skill vs. luck/market?

Alpha is the return that remains after stripping out what the market handed everyone. CAPM (see section 2.5) predicts the return a portfolio *should* have made given its market exposure. Alpha is the difference between prediction and reality.

```
Alpha = Actual Return − CAPM-Predicted Return
```

**Concrete example**: If CAPM predicts a portfolio should return 12% (given its beta and the market's performance), and the portfolio actually returns 18%, the alpha is +6%. That 6% is attributable to skill — the model found something the market hadn't yet priced in.

**Zero or negative alpha**: You're not adding value. A client would be better off in a passive index fund at a fraction of the cost.

**Alpha is the entire business case** for your system. The beta component of any return is free and replicable. Alpha is what funds charge 2-and-20 for, and what your automated system is designed to discover continuously.

---

### 2.3 Beta

**The question it answers**: How sensitive is this portfolio to market movements?

Beta measures how much of a portfolio's return is explained by the broader market moving up or down — the "weather" that affects everything.

| Beta Value | Meaning |
|---|---|
| 1.0 | Moves exactly with the market |
| 1.5 | 10% market rise → 15% portfolio rise (and vice versa) |
| 0.5 | Half as volatile as the market |
| 0.0 | Completely uncorrelated to market movements |
| -1.0 | Moves opposite to the market |

**Why high beta is not the same as alpha**: Anyone can achieve high beta by borrowing money and buying index funds. A portfolio returning 15% with beta 2.0 in a 10% market year has zero alpha — it's all leverage. Clients can replicate that for almost nothing.

**Why quant funds target beta near zero**: See section 2.5.

---

### 2.4 How They Connect

The one paragraph to memorize:

> A portfolio's Sharpe Ratio has exactly two engines driving it: the beta engine (how much the rising market lifts you) and the alpha engine (how much your proprietary signals lift you above that). Since beta comes with volatility — and volatility is the Sharpe denominator — increasing beta often *lowers* your Sharpe even as it raises your raw returns. The only way to raise Sharpe without adding volatility is to find genuine alpha. That is why this system exists: automated, continuous discovery of high-alpha, low-beta signals that humans couldn't find fast enough manually.

---

### 2.5 CAPM and Market-Neutral Investing

**What CAPM is**: The Capital Asset Pricing Model is the framework that says: given how much market risk an investment takes on (beta), here is the return it *should* have earned. Any return above that prediction is skill. Any return below is underperformance vs. simply buying an index.

**The rain analogy**: Think of the stock market as weather. On sunny days (bull markets), almost every stock rises. On rainy days (crashes), almost every stock falls. Beta measures how much each stock amplifies or dampens the weather. A market-neutral portfolio is one where you've *engineered away* the weather entirely — returns come in regardless of whether it's sunny or raining.

**Why market-neutral, not just low-beta**: Low beta is still a weather bet, just a smaller one. A fund with beta 0.3 still loses money in a crash. Worse, clients can achieve low-beta exposure themselves by mixing an index fund with cash — they don't need to pay 2-and-20 for it.

**How market neutrality is achieved — the long/short mechanism**:

```
Long positions:  Buy stocks your signal says will outperform → $1,000,000
Short positions: Sell (borrowed) the S&P 500 futures as hedge → ~$1,000,000
                 Also short weak competitors your signal identifies
```

If the market crashes 15%, your long positions fall — but your short hedge gains roughly the same amount. The market risk cancels. What remains is the difference in performance between your specific picks and the market: pure alpha.

**The three market scenarios:**

| Scenario | High-Beta Fund (β=2.0) | Conservative Fund (β=0.5) | Market-Neutral Fund (β≈0) |
|---|---|---|---|
| Bull (+20%) | +40% | +10% | +8% (all alpha) |
| Flat (0%) | 0% | 0% | +8% (all alpha) |
| Bear (−20%) | −40% | −10% | +8% (all alpha) |

The flat and bear scenarios explain everything. The market-neutral fund earns +8% *regardless* of market conditions because those returns come entirely from skill, not weather.

---

### 2.6 Information Coefficient (IC)

**The question it answers**: Did your signal actually predict what it claimed to predict?

Your alpha generator produces a formula that scores 500 stocks from -1.0 (sell) to +1.0 (buy). One week later, you look at what actually happened. Did the stocks you scored highly actually go up more than the stocks you scored low?

The IC is the **correlation** between your signal's scores and the actual subsequent returns, measured across many stocks and many time periods.

**The scale:**

| IC Value | Interpretation |
|---|---|
| +1.0 | Perfect prediction (never happens in real markets) |
| 0.15–0.20 | Very strong — exceptional and rare |
| 0.10–0.15 | Strong — worth serious investment |
| 0.05–0.10 | Weak but real — where most professional signals live |
| 0.00–0.05 | Noise — discard or investigate further |
| Negative | Inverted signal — potentially valuable if you flip the scores |

**Why IC of 0.10 is enough to make money**: This is genuinely counterintuitive. An IC of 0.10 means your signal explains about 1% of return variance — statistically tiny per trade. But applied across 500 stocks every trading day for three years, the slight but consistent tilt in your favor accumulates into a substantial return advantage. Quant funds run on breadth: thousands of small bets where each has modest IC, and the law of large numbers does the rest.

**Two ways IC is used in your system:**

1. **Initial screening (Screener Agent)**: Any formula with backtest IC below ~0.04 is discarded immediately. Not worth the position.
2. **IC consistency over time**: A formula showing IC = 0.18 in one specific year but IC ≈ 0 in all others is not a reliable signal — it found a quirk of that year's data. The metric that matters is IC *stability* across multiple market periods. This is how you defend against overfitting challenges.

**IC decay**: Every signal's IC tends to drift toward zero over time as competitors discover and trade the same pattern. This is alpha decay.

---

### 2.7 Alpha Decay

**The core mechanism**: The moment a profitable pattern becomes known, the act of trading it destroys the pattern. Markets are competitive ecosystems — every dollar of alpha is taken from someone else, and that someone eventually figures out what's happening.

**Three decay channels:**

**1. Crowding**: As more funds discover the same signal, they all try to buy the same stocks simultaneously. This buying pressure moves prices *before* the predicted outcome arrives, partially pricing in the expected return in advance. The alpha shrinks because you're now buying at a worse price than the original discoverer.

**2. Regime change**: Markets evolve. A signal built on human trading behavior degrades as algorithmic trading dominates its target stocks. A signal exploiting slow information diffusion collapses when news terminals become ubiquitous. The underlying mechanism the signal exploited simply stops existing.

**3. Arbitrage completion**: Some anomalies exist because of persistent behavioral bias — investors systematically overreact or underreact. As awareness of the bias grows through academic papers, the bias itself partially corrects.

**Decay speed taxonomy:**

| Speed | Typical Timeline | Signal Type | Example |
|---|---|---|---|
| Ultra-fast | Hours to days | HFT microstructure, intraday momentum | Order flow imbalance |
| Fast | Months to 2 years | News sentiment, social media, standard earnings metrics | FinBERT on Reuters |
| Medium | 2–10 years | Alternative data with moderate replication barrier | Satellite imagery |
| Slow | 10–50+ years | Structural behavioral biases | Post-earnings announcement drift |

**Real-world decay examples:**

**Weekend Effect (IC ≈ 0.12 in 1973 → IC ≈ 0.00 by 2003)**
Stocks historically rose on Fridays and fell on Mondays. Documented in a 1973 academic paper. Survived for 25 years because execution was slow. Once electronic trading arrived, the arbitrage completed in milliseconds and the IC collapsed to zero. The canonical example of an anomaly arbitraged to death.

**Post-Earnings Announcement Drift (IC ≈ 0.24 in 1968 → IC ≈ 0.12 today)**
Companies that beat earnings expectations continue outperforming for 60–90 days. Documented in 1968. Still partially alive 50+ years later because the underlying mechanism — investors anchoring to analyst estimates and updating beliefs slowly — is a structural behavioral feature, not an information asymmetry. Behavioral biases decay more slowly than information edges. IC has compressed from ~0.24 to ~0.12 as more funds trade it.

**News Sentiment (IC ≈ 0.14 in 2010 → IC ≈ 0.06 today)**
First-mover NLP teams applying sentiment to Reuters/Bloomberg feeds earned IC around 0.14 in 2010–2014. GPT-4 and open-source LLMs made sophisticated news parsing accessible to any team with an API key — barrier to entry collapsed. Basic FinBERT sentiment on public news is now semi-commoditised, particularly for large-cap stocks.

**What determines decay speed:**
- **Replication barrier**: If your signal requires $2M of infrastructure and 18 months of ML work, decay is slow. If it requires an API key and 100 lines of Python, decay is fast.
- **Capital capacity**: A signal that only works on $10M before market impact destroys it saturates with fewer competitors.
- **Behavioral vs. informational**: Information edges decay fast (information spreads). Behavioral edges decay slowly (human psychology changes over generations).
- **Publication**: Academic papers kill signals. IC dropped noticeably each time a major confirmation paper appeared documenting the weekend effect.

**Implication for your system**: The GNN supply chain ripple layer is your slowest-decaying component — high replication barrier, behavioral + informational mechanism. Standard FinBERT on news is your fastest-decaying component — should be treated as one weak factor among many, not a primary signal.

---

## 3. System Architecture

### 3.1 Pipeline Overview

```
┌─────────────────────────────────────────────────────────┐
│                    DATA INGESTION LAYER                  │
│  News + Filings + Earnings Audio + Job Postings +        │
│  Price/Volume + Supply Chain Graph + Patent Data         │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│               EXTRACTION AGENT (Miner)                   │
│  FinBERT sentiment scoring                               │
│  Earnings call prosodic feature extraction (Whisper)     │
│  EDGAR filing language drift computation                 │
│  GNN ripple risk scoring                                 │
│  Structured signal output → signal store                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│           ALPHA GENERATOR AGENT                          │
│  LLM-driven formula generation from DSL vocabulary       │
│  Evolutionary/genetic search over formula space          │
│  Generates candidate alpha expressions                   │
│  DSL operators: Rank(), DecayLinear(), Correlation(),    │
│  StdDev(), ZScore(), Delta(), SignedPower(), etc.        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│           BACKTESTER AGENT (Screener)                    │
│  Historical simulation on out-of-sample data             │
│  Computes: IC, Sharpe, max drawdown, turnover            │
│  Applies multiple testing correction (Bonferroni/BH)     │
│  Point-in-time data guarantees (no look-ahead bias)      │
│  Stores results in alpha result database                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│           GATEKEEPER AGENT                               │
│  IC threshold filter (minimum 0.04 sustained)            │
│  Sharpe threshold filter (minimum 1.0)                   │
│  Turnover penalty (high turnover = realistic cost drag)  │
│  Correlation check (don't add redundant signals)         │
│  Passes survivors to portfolio layer                     │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│           PORTFOLIO OPTIMISER                            │
│  Mean-variance optimisation (PyPortfolioOpt)             │
│  Transaction cost constraints                            │
│  Beta neutralisation (target β ≈ 0)                      │
│  PPO-based dynamic weight adaptation (future)            │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Agent Roles

| Agent | Responsibility | Key Output |
|---|---|---|
| Extraction Agent | Turn raw data into structured signals | Scored signal vectors per company per day |
| Alpha Generator | Produce candidate alpha formulas | DSL expressions for backtesting |
| Backtester | Test formulas on historical data honestly | IC, Sharpe, drawdown per formula |
| Gatekeeper | Accept or reject formulas from backtester | Approved alpha formula library |
| Portfolio Optimiser | Combine surviving alphas into positions | Daily target weights per ticker |

### 3.3 Data Flow

The key architectural principle: **every agent communicates through structured data stores, not direct calls.** This allows agents to run asynchronously, restart independently, and be replaced or upgraded without breaking the pipeline.

- Signal store: time-indexed, per-company signal scores (vector database + SQL)
- Alpha library: all approved formulas with their IC history (SQL)
- Backtest results: every formula ever tested, whether approved or rejected (SQL)
- Position targets: daily weight output for execution layer (SQL)

---

## 4. Comparison with Existing Systems

### 4.1 Alpha-GPT

The most comparable published system to your proposed architecture. Developed by researchers linked to WorldQuant. Uses prompt engineering and LLMs to generate creative trading signals, validated through an alpha mining pipeline. Key feature: a "knowledge compilation module" that retrieves similar successful alphas as few-shot examples before each LLM generation call.

**How yours compares**: Essentially the same pipeline concept. Your Gatekeeper feedback loop — where failed formulas inform future generation — is a meaningful addition Alpha-GPT's original version lacks. The GNN and path signature layers are not present in Alpha-GPT.

### 4.2 Multi-Modal Multi-Agent Research (ACL 2025)

A published multi-agent system generating alpha factor candidates from diverse financial data, filtering on market status and predictive quality metrics, with dynamic weight optimisation adapting to market conditions. Reported 53% cumulative return on Chinese markets.

**How yours compares**: Architecture is nearly identical. The key difference is that this paper implements learned weight adaptation as a core component, while your system describes PPO-based adaptation as a future component. Consider this a roadmap for what the portfolio layer evolves into.

### 4.3 MarketSenseAI 2.0

GPT-4 based system integrating RAG over diverse financial datasets for portfolio optimisation. More explicit about signal extraction auditing than comparable systems.

**How yours compares**: Your news sourcing layer is more explicit about the signal extraction step, which is an advantage for explainability and auditability.

### 4.4 Where Your Approach Stands

**Genuine differentiators** (hard to replicate):
- GNN supply chain ripple-effect layer — rare in open implementations, high engineering barrier
- Path signatures for time-series encoding — almost never combined with LLM alpha search in published work
- Earnings call audio prosodic features — novel data source with documented IC persistence

**Areas of parity** (you're doing what the field does):
- LLM-driven formula generation from DSL
- Multi-agent pipeline with backtester-in-the-loop
- FinBERT sentiment scoring

**Known gaps vs. production systems**:
1. **Look-ahead bias protection**: Not explicitly addressed in original document. LLMs can inadvertently incorporate future returns into current forecasts. Requires explicit point-in-time data guarantees
2. **Multiple testing correction**: Selecting top 10 formulas from 1,000 without Bonferroni or Benjamini-Hochberg correction inflates false discovery rate
3. **Transaction costs in fitness function**: Sharpe without transaction costs will select for high-turnover strategies that are actually unprofitable live
4. **Regime detection**: Many alphas that work in calm markets collapse during crises; the system has no regime awareness yet

---

## 5. Tooling and Dev Stack

### 5.1 Current Stack Assessment

| Tool | Purpose | Assessment |
|---|---|---|
| yfinance → Polygon.io | Price data | ✅ Correct progression |
| FinBERT (ProsusAI) | Financial sentiment | ✅ Right choice — domain-specific beats general GPT for this |
| LangGraph | Multi-agent orchestration | ✅ Well-suited to this pipeline |
| PyPortfolioOpt + CVXPY | Portfolio optimisation | ✅ Right two-tier approach |
| gplearn | Genetic programming | ✅ Produces human-readable expression trees |
| Prefect | Workflow scheduling | ⚠️ Overlaps with LangGraph — see note below |
| pandas/numpy for backtesting | Historical simulation | ⚠️ Works but means reimplementing everything manually |

### 5.2 Missing Tools

**Vector database**: No store for news embeddings, historical alpha formula results, or semantic search over past signals. Without Chroma (local prototype) or Qdrant/Weaviate (production), you'll end up with ad hoc in-memory stores that break on restart. Add **Chroma** immediately.

**Backtesting framework**: "pandas or numpy" means manually reimplementing vectorised return calculation, position management, drawdown metrics, and cross-sectional IC computation. **VectorBT** is the strongest current option — far faster than loop-based Backtrader for the cross-sectional alpha testing you're doing.

**Alpha result persistence**: Every formula the genetic engine tests needs IC, Sharpe, decay curve, and generation parameters stored persistently. Without this, you cannot analyse which mutation patterns improve alphas over time or retrain the generator on its own successes. **SQLite** for prototype, **DuckDB** for production (columnar — much faster for the analytical queries you'll run).

### 5.3 Revised Recommended Stack

```
Data Sources
├── yfinance (prototyping price data)
├── Polygon.io (production price data)
├── SEC EDGAR API (free — filings, MD&A extraction)
├── Earnings call audio (public company IR pages)
└── USPTO Patent API (free)

Feature Engineering
├── ProsusAI/FinBERT (sentiment scoring)
├── OpenAI Whisper (earnings call audio transcription + timestamps)
└── PyTorch Geometric / GraphSAGE (GNN supply chain signals)

Alpha Generation
├── LangGraph (multi-agent orchestration)
├── gplearn (genetic programming for formula evolution)
└── Claude API / GPT-4 (LLM formula generation from DSL)

Backtesting
└── VectorBT (vectorised, fast, cross-sectional IC native)

Storage
├── Chroma (vector embeddings — news, formula similarity)
├── DuckDB (alpha result store — analytical queries)
└── PostgreSQL (production — positions, audit trail)

Portfolio Optimisation
├── PyPortfolioOpt (standard mean-variance)
└── CVXPY (custom constraint problems)

Scheduling (pick one, not both)
└── LangGraph (handles flow control + scheduling in prototype)
    → Add Prefect only when production scheduling is needed

Monitoring
└── Weights & Biases (model IC tracking over time)
```

**Prefect/LangGraph note**: They can coexist but you'll need to be deliberate about the boundary. For a solo vibe-coded project, start with LangGraph only. Add Prefect when you genuinely need production-grade scheduling, retry logic, and observability — not before.

---

## 6. Data Strategy

### 6.1 The Decay Problem with Standard News

Basic FinBERT sentiment on Reuters and Bloomberg headlines has been traded systematically since approximately 2015. The IC on large-cap S&P 500 stocks is now compressed to the 0.05–0.07 range. This doesn't mean discard it — it means treat it as one weak factor among many, not a differentiator.

The core principle for data sourcing: **the harder the data is to acquire, clean, and interpret, the slower its IC decays.** Bloomberg terminals are commoditised. Sources requiring significant engineering to parse or domain expertise to interpret correctly have higher replication barriers and longer alpha half-lives.

### 6.2 Slow-Decaying Data Sources

**Tier 1 — High signal, buildable by a solo developer, free data:**

**Earnings call audio — prosodic features**

The words a CEO says are priced in within milliseconds of a transcript appearing. What isn't priced in as efficiently: *how* they say it. Speech rate changes, increased filler words, longer pauses before answering analyst questions, voice pitch variance when discussing specific topics.

- Data source: Company IR pages (public, SEC-required)
- Extraction tool: OpenAI Whisper (free, open source) → word-level timestamps
- Features: pause duration before answers, filler word frequency, speech rate per section, cross-quarter changes in vocal patterns
- Why it decays slowly: Requires audio processing infrastructure and domain expertise to interpret; not yet commoditised

**EDGAR filing language drift**

10-K and 10-Q filings are free via SEC EDGAR. The alpha isn't in reading them — everyone does that. It's in tracking how the *language changes* quarter over quarter. A company quietly removing "strong demand environment" from three consecutive filings and replacing it with "navigating market conditions" is signalling something that doesn't appear in any headline.

- Data source: SEC EDGAR full-text search API (free, no key required)
- Extraction: Diff-based NLP pipeline over consecutive filings, section by section
- Features: semantic drift score, sentiment delta vs. prior quarter, new risk disclosures introduced, phrases removed
- Why it decays slowly: Requires building and maintaining a diffing pipeline over structured SEC documents; most teams don't bother

**Job posting signals**

Companies list open roles publicly. A semiconductor firm tripling its Taiwan-based supply chain operations headcount six months before anyone reports a capacity expansion is showing you the capex decision before it's announced.

- Data source: LinkedIn (scraped carefully), Indeed, company career pages
- Extraction: NLP classification of job titles + locations + seniority signals
- Features: hiring velocity by function, geographic hiring shift, seniority mix changes
- Why it decays slowly: Hiring cycles are inherently slow-moving; the signal is forward-looking by months, not days

**Patent filing velocity**

USPTO publishes all patent applications with an 18-month delay from filing. Sudden acceleration in filings in a specific technology domain — particularly for companies not known for that domain — is a leading indicator of strategic pivots the market hasn't priced.

- Data source: USPTO Patent Full-Text Database (free bulk download)
- Extraction: NLP classification by technology domain, company entity matching
- Features: filing velocity by domain, domain novelty score (how different from historical filings), cross-company citation patterns
- Why it decays slowly: Requires understanding what the patents mean technically; LLM interpretation is the differentiating layer

**Tier 2 — Higher effort, meaningful if achievable:**

**Supply chain customs records**: US Census Bureau makes US import customs records public (painful to parse). Shows actual shipment volumes between companies. Panjiva/S&P Global sells the cleaned version commercially.

**Satellite imagery**: Google Earth Engine provides Sentinel-2 imagery for academic/research use (free). A focused implementation — parking lots at 50 specific retail locations, or port traffic at 5 key industrial ports — is buildable for a solo developer with CV skills.

### 6.3 Tier Rankings for a Solo Developer

Starting priority given engineering effort vs. expected IC half-life:

1. **Earnings call audio prosodic features** — free data, real ML work, documented IC persistence, no competitors at small scale
2. **EDGAR language drift** — free data, engineering challenge rather than access barrier, complements your LLM layer directly
3. **Job posting signals** — publicly accessible, slow-moving by nature (good: slow decay), meaningful for your supply chain graph as a validation signal
4. **Patent filing velocity** — USPTO is free, classification requires your LLM to earn its keep; genuinely hard to replicate at scale

---

## 7. GNN Module — Semiconductor Supply Chain

### 7.1 Why GNN and Why Semiconductors First

**Why GNN**: Standard alpha factors treat each stock independently. A supply chain shock at TSMC affects Nvidia, AMD, Apple, Qualcomm, and dozens of others in a predictable dependency cascade — but only if your model can "see" the graph structure connecting them. A Graph Neural Network can propagate signals through this network via message passing: a liquidity stress indicator at a Tier 0 foundry gets reflected in the node representations of Tier 1 chip designers downstream from it.

**Why semiconductors specifically**:
- The graph is small and tractable (~80–120 companies globally)
- Relationships are well-documented in 10-K disclosures, analyst reports, and academic supply chain research
- Ripple effects are dramatic, well-studied, and occur on measurable timescales (days to weeks)
- Historical disruption events are numerous and documented (chip shortage 2021, Renesas fire, ASML export restrictions, etc.)
- The sector is central to current market narratives (AI infrastructure, geopolitical risk)

**Why this decays slowly**: Building a credible semiconductor supply chain GNN requires proprietary graph construction, continuous relationship maintenance, and meaningful ML infrastructure. This raises the replication barrier substantially compared to sentiment on public news.

### 7.2 Five-Step Build Strategy

**Step 1 — Constrain the graph aggressively**

Start with 80 nodes and ~200 edges. Do not attempt the full S&P 500 until the small graph is working. Build coverage across four tiers:
- Tier 0: Foundries (TSMC, Samsung, GlobalFoundries) and Equipment (ASML, AMAT, LRCX)
- Tier 1: Fabless designers (Nvidia, AMD, Qualcomm, Apple, Broadcom, ARM)
- Tier 2: Packaging/assembly (ASE, Amkor) and Materials (Entegris, Shin-Etsu)
- Tier 3: OEMs and end consumers (Tesla, Dell, Microsoft, Google, Meta)

**Step 2 — Use PyTorch Geometric (PyG) with GraphSAGE**

GraphSAGE is the right architecture for this use case because it's designed for inductive learning — it generalises to nodes it hasn't seen during training. This matters because companies enter and exit the universe. Use `SAGEConv` from PyG. Two message-passing layers.

**Step 3 — Define node features carefully, not ambitiously**

Start with 7 features per node. All freely available, all easily updated:

| Feature | Source | Rationale |
|---|---|---|
| `ret_20d` | yfinance | 20-day trailing return |
| `vol_20d` | yfinance | 20-day return volatility |
| `ret_5d` | yfinance | Short-term momentum |
| `vol_ratio` | yfinance | vol_5d / vol_60d — volatility regime |
| `log_mktcap` | yfinance | Size normalisation |
| `rsi_14` | yfinance | Overbought/oversold indicator |
| `finbert_score` | SEC EDGAR + FinBERT | Sentiment from latest 10-Q MD&A |

**Step 4 — Define edges with weights, not binary connections**

Each edge carries two attributes:
- `weight` (0.0–1.0): dependency strength — what fraction of Company B's inputs come from Company A, sourced from 10-K supplier disclosures
- `substitutability` (0.0–1.0): how easily Company B can replace Company A — 0.02 for ASML EUV (monopoly), 0.8 for commodity chemical suppliers

Anchor edges to build from (minimum 200 total):

| Source | Target | Weight | Substitutability | Relationship |
|---|---|---|---|---|
| TSMC | NVDA | 0.95 | 0.05 | Sole foundry for H100/H200 |
| TSMC | AMD | 0.90 | 0.08 | Primary foundry |
| TSMC | AAPL | 0.90 | 0.10 | A-series, M-series chips |
| ASML | TSMC | 0.95 | 0.02 | EUV lithography monopoly |
| ASML | GFS | 0.70 | 0.10 | DUV/EUV equipment |
| NVDA | MSFT | 0.60 | 0.20 | GPU supply for Azure AI |
| NVDA | GOOGL | 0.55 | 0.25 | GPU supply for GCP |
| NVDA | META | 0.65 | 0.20 | GPU for AI infrastructure |
| ARM | QCOM | 0.90 | 0.15 | Architecture licensing |
| ARM | AAPL | 0.95 | 0.05 | Architecture licensing |

**Step 5 — Training objective that creates genuine alpha signal**

The GNN needs a learning objective grounded in financial outcomes, not just graph structure. Training objective: given a shock applied to node X, predict the abnormal return (actual return minus market return, using SPY as proxy) of connected nodes over the following 5 and 10 trading days.

Historical training data: documented supply chain disruption events in semiconductors, 2015–2024. Each event becomes one training sample — the graph at shock date, with a shock indicator added to the affected node's feature vector, trained to predict downstream abnormal returns.

### 7.3 Architecture Decisions

```
Input: Node features [n_nodes, 9]  (7 base + 2 shock indicator features)
       Edge index [2, n_edges]
       Edge weights [n_edges, 2]   (weight, substitutability)

Layer 1: GraphSAGE (hidden_dim=64, aggregation='mean')
         + Skip connection (residual from input)
         + Dropout (p=0.3)
         + ReLU

Layer 2: GraphSAGE (hidden_dim=64 → output_dim=2)

Output: [n_nodes, 2]  → [abnormal_ret_5d, abnormal_ret_10d]
```

**Key choices explained:**
- **Mean aggregation** (not max): We want average neighbor influence, not worst-case
- **2 layers** (not more): The semiconductor graph has diameter ~4; two hops captures most indirect relationships without over-smoothing
- **Residual connection**: Stabilises training, lets the model learn incremental adjustments over base features
- **Train loss on non-shocked nodes only**: The shocked node is the input signal, not a prediction target

### 7.4 Project File Structure

```
semiconductor_gnn/
├── data/
│   ├── universe.py          # 80-company universe with tiers and roles
│   ├── edges.py             # 200+ supply chain edges with weights
│   ├── price_features.py    # yfinance rolling features + normalisation
│   ├── sentiment_features.py# EDGAR → FinBERT → sentiment scores + cache
│   └── shocks.py            # Historical disruption event catalogue
├── graph/
│   ├── builder.py           # Assembles PyG Data object
│   └── dataset.py           # PyG Dataset for shock-event training
├── model/
│   ├── graphsage.py         # Model definition (2-layer GraphSAGE)
│   └── train.py             # Training loop: MSE loss, IC metric, checkpointing
├── inference/
│   └── scorer.py            # Public API: RippleRiskScorer class
├── tests/
│   └── test_graph.py        # Smoke tests
├── config.py                # All constants centralised
└── requirements.txt
```

### 7.5 The Public API (Most Important File)

The multi-agent system imports `RippleRiskScorer` from `inference/scorer.py`. This is the contract between the GNN module and everything built on top of it. Do not change this interface once established.

```python
from inference.scorer import RippleRiskScorer

scorer = RippleRiskScorer(checkpoint_path="model/checkpoints/best.pt")

# Daily scoring — called by the orchestrator each morning
df = scorer.score("2024-11-15")
# Returns DataFrame: ticker | company_name | tier | role |
#   ripple_risk_5d | ripple_risk_10d | confidence |
#   top_upstream_risk | data_freshness

# Scenario analysis — simulate a specific shock
df_shocked = scorer.score_shock("2024-11-15", "TSM", severity=0.9)
# Returns same schema with shock-propagated scores

# Explain a path between two companies
path = scorer.get_supply_chain_path("TSM", "META")
# Returns: [{"ticker": "TSM", "edge_weight": 0.95, "relationship": "foundry"},
#           {"ticker": "NVDA", ...}, {"ticker": "META", ...}]

# Orchestrator startup check
status = scorer.health_check()
# Returns: {"model_loaded": bool, "graph_nodes": int, ...}
```

### 7.5 Success Criteria

The GNN module is complete when:
1. `test_graph.py` passes with no errors
2. `health_check()` returns `model_loaded: true`
3. `score("2024-01-15")` returns a 80-row DataFrame with all columns populated
4. `score_shock("2024-01-15", "TSM", 0.9)` produces meaningfully different scores from `score("2024-01-15")` — specifically, TSMC's Tier 1 customers (NVDA, AAPL, AMD, QCOM) should show elevated ripple risk
5. Training reaches `val IC > 0.05` on held-out shock events (report honestly if not — do not tune to hit the target)

---

## 8. Known Gaps and Critical Risks

### Look-Ahead Bias

**The problem**: The most common way backtests lie. Future data accidentally bleeds into past calculations. An LLM generating alpha formulas from news articles can inadvertently incorporate future return information into current forecasts if the data pipeline isn't carefully designed with point-in-time guarantees.

**The fix**: Every data fetch must be keyed to `as_of_date` — the date the signal *would have been available* to a live trader, not the date the information became known in hindsight. SEC filings have known delay patterns; price data must use `close` prices on the signal date, not `open` prices on the following day. VectorBT has point-in-time guarantees built in; a manual pandas backtester requires explicit discipline.

### Multiple Testing Problem

**The problem**: If you generate and test 1,000 alpha formulas, some will appear to work by pure statistical chance — even if they have zero real predictive power. With a standard significance threshold of p < 0.05, you'd expect 50 false positives among 1,000 tests even if every formula is random noise.

**The fixes**:
- **Bonferroni correction**: Divide your significance threshold by the number of tests. If testing 1,000 formulas, require p < 0.00005 instead of p < 0.05. Conservative — may discard genuine signals
- **Benjamini-Hochberg (FDR)**: Controls the expected proportion of false discoveries among accepted formulas. Less conservative than Bonferroni, better suited to large-scale alpha search
- **Out-of-sample holdout**: The most robust protection. Test formulas on a period entirely unseen during generation. If the IC holds up on true out-of-sample data, it's probably real

**Where to implement**: In `model/train.py` and the Backtester Agent — apply BH correction when selecting from a batch of tested formulas.

### Transaction Costs

**The problem**: A formula with Sharpe 2.0 on daily signals that requires 30% portfolio turnover per week will be unprofitable after realistic spread and slippage.

**The fix**: Add a turnover penalty to the backtester fitness function. Estimated transaction cost = (turnover × 0.05%) for liquid large-caps, higher for small-caps. Any formula whose Sharpe drops below 1.0 after applying realistic transaction costs should be rejected.

### Alpha Crowding in Your Own System

**The subtle problem**: If you accept 10 alpha formulas that are all highly correlated with each other (they all essentially say "buy momentum stocks"), your portfolio has concentrated risk disguised as diversification.

**The fix**: Before accepting a new formula into the live library, check its correlation with all existing approved formulas. Target correlation below 0.4. A new formula that adds IC but also adds 0.85 correlation to something already in the library doesn't add much diversification value.

---

## 9. Theory Learning Roadmap

Organised by priority. The first two layers are required before any demo, investor conversation, or technical interview.

### Layer 1 — Core Finance Intuition (1–2 weeks)

These are the concepts you'll be asked about in any conversation about the project. Can't skip.

| Concept | What to Understand | Why It Matters |
|---|---|---|
| Sharpe Ratio, Alpha, Beta | See sections 2.1–2.3 above | The three numbers anyone evaluating your system will ask about first |
| CAPM and market neutrality | See section 2.5 | Core motivation for targeting beta ≈ 0 |
| Information Coefficient | See section 2.6 | The fitness function for every alpha formula |
| Alpha decay mechanics | See section 2.7 | The core problem your system solves |

### Layer 2 — System Architecture Concepts (2–3 weeks)

Required to explain your own project coherently.

| Concept | Key Points |
|---|---|
| Backtesting and its pitfalls | Look-ahead bias, survivorship bias, overfitting. Know all three cold |
| Multi-agent system design | Why split the pipeline across agents; role of feedback loops |
| Genetic/evolutionary search | Expression trees, mutation, fitness selection; what gplearn actually does |
| Domain-Specific Language (DSL) | Why constraining LLM output to a vocabulary of operators matters |
| FinBERT and NLP sentiment | What a domain-specific BERT model outputs, its limitations on novel events |
| Portfolio optimisation basics | Efficient frontier, mean-variance, why you can't "bet everything on the best signal" |

### Layer 3 — Advanced Techniques in Your System (3–5 weeks)

Differentiators. Learn these to sound genuinely sophisticated.

| Concept | Key Points |
|---|---|
| Graph Neural Networks | Message passing; nodes as companies, edges as relationships; why GNN sees ripple effects |
| GraphSAGE specifically | Inductive learning; aggregation strategies; why suited to financial graphs |
| Path signatures | What a truncated signature captures about a price path; why order of events matters |
| PPO reinforcement learning | Intuition: reward profitable behavior, penalise losses, update policy — the "coach" for weight adaptation |
| Multiple testing correction | Why 1,000 tested formulas require statistical correction; Bonferroni vs. Benjamini-Hochberg |

### Layer 4 — Production Awareness (Ongoing)

Not required to build the prototype. Required to sound credible in serious technical conversations.

| Concept | Key Points |
|---|---|
| Market microstructure | Slippage, bid-ask spread, transaction costs; why Sharpe 1.5 in backtest can be unprofitable live |
| Market regimes | Bull/bear/high-volatility regimes; alphas that work in calm markets can collapse in crises |
| Regulatory basics | Market manipulation rules; wash trading; front-running; what applies to AI-generated signals |

---

## 10. Interview Preparation — Key Q&A

**"What's the difference between alpha and return?"**
Return is the total number. Alpha is only the part earned through skill, after stripping out what the market handed everyone. A fund returning 15% in a year the market returned 20% has negative alpha — it underperformed relative to the risk it took.

**"Why not just maximize beta if the market generally goes up?"**
Beta is symmetric. If you lever up to beta 2.0 to capture more upside, you also double your downside. You're not generating value; you're amplifying market exposure. Anyone can do that with leverage. Alpha is the only source of uncorrelated return.

**"What's a good Sharpe Ratio in practice?"**
It depends on strategy and time horizon. Daily-rebalancing quant strategies often target 1.5–2.0. Long-only equity funds consider 1.0 respectable. Claims above 3.0 without explanation are a red flag for backtest overfitting.

**"How does your system ensure the alpha it finds is real and not statistical noise?"**
Three mechanisms: backtesting on out-of-sample data the generator never saw, requiring IC consistency across multiple market periods (not just one lucky year), and applying Benjamini-Hochberg correction when selecting from a large pool of candidate formulas.

**"If your backtested Sharpe is 2.0, what do you expect live performance to be?"**
Significantly lower. A 2.0 backtest Sharpe translating to 1.0–1.2 live is considered a success. The gap comes from transaction costs, slippage, market impact, look-ahead bias in the backtest, and the fact that other traders partially arbitrage the signal before execution.

**"Why would a formula with very high returns be rejected by your system?"**
If those returns came with enormous volatility, the Sharpe Ratio would be low. The Gatekeeper filters on risk-adjusted return, not raw return. A formula making 500% one year and losing 400% the next has negative practical value regardless of the average.

**"What differentiates your system from basic FinBERT sentiment trading?"**
FinBERT on standard news is now semi-commoditised — IC in the 0.05–0.07 range on large caps. The differentiating components are: (1) the GNN supply chain ripple layer, which captures second-order effects competitors miss and has a high replication barrier, and (2) novel data sources — earnings call prosodic features and EDGAR language drift — that require significant engineering to extract and are not yet commoditised.

**"What's your biggest technical risk?"**
Look-ahead bias in the backtesting pipeline. It's the most common way quantitative research systems produce results that look good historically but fail live. We're addressing it through explicit point-in-time data guarantees and VectorBT's built-in safeguards.

---

## 11. Build Sequence

The recommended order of development, each stage producing a testable artifact.

```
Phase 1 — GNN Foundation (current)
├── Semiconductor universe + edge list (data/universe.py, data/edges.py)
├── Price feature pipeline (data/price_features.py)
├── EDGAR sentiment pipeline (data/sentiment_features.py)
├── Graph assembly + validation (graph/builder.py)
├── Shock event dataset (data/shocks.py, graph/dataset.py)
├── GraphSAGE model + training (model/)
└── RippleRiskScorer public API (inference/scorer.py)
    ✓ Milestone: score_shock("2024-01-15", "TSM", 0.9) shows credible propagation

Phase 2 — Backtesting Infrastructure
├── VectorBT integration with IC computation
├── Point-in-time data guarantees
├── Transaction cost model
└── Alpha result persistence (DuckDB)
    ✓ Milestone: Can honestly evaluate one alpha formula end-to-end

Phase 3 — Alpha Generation
├── DSL vocabulary definition
├── LLM formula generation (LangGraph + Claude API)
├── gplearn genetic search
└── Chroma vector store for formula similarity
    ✓ Milestone: System generates 100 candidate formulas overnight

Phase 4 — Gatekeeper + Multi-Agent Orchestration
├── IC threshold filter
├── Sharpe + turnover filter
├── Multiple testing correction (BH)
├── Correlation check against existing formula library
└── Full LangGraph pipeline connecting all agents
    ✓ Milestone: End-to-end run from data ingestion to approved alpha formula

Phase 5 — Slow-Decay Data Sources
├── Earnings call audio → Whisper → prosodic features
├── EDGAR language drift pipeline
└── Job posting signal extraction
    ✓ Milestone: IC comparison between FinBERT baseline vs. novel sources

Phase 6 — Portfolio Layer
├── PyPortfolioOpt mean-variance optimisation
├── Beta neutralisation
└── PPO-based dynamic weight adaptation (stretch goal)
    ✓ Milestone: Full backtest of combined alpha library as managed portfolio
```

**The principle governing sequence**: Each phase produces something testable and demonstrable before the next begins. Phase 1 can be shown to anyone as a standalone system. This matters for a solo developer — you always have something working, never a half-finished system that can't be demonstrated.

---

*Document compiled from project planning session. The GNN Claude Code prompt is a separate file: `gnn_claudecode_prompt.md`*
