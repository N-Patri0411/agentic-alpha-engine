# Backtesting and Supply-Chain Scenarios

## What backtesting means

Backtesting means pretending to be at a date in the past and using only information that was available then. We calculate a factor score, wait for the next price movement, and compare the score with what actually happened.

The most important safety rule is no future information. Every observation has an `available_at` timestamp. A run with an earlier `as_of_time` must reject it.

## Current demo data

The current demo files are:

- `data/demo_prices.csv`
- `data/demo_factors.csv`

They are synthetic. They intentionally make high-scored companies rise and low-scored companies fall so the tests can confirm that the backtest implementation behaves as expected.

Price rows have this shape:

```text
date,ticker,close,available_at
2024-01-02,NVDA,200,2024-01-02T21:00:00+00:00
```

Factor rows have this shape:

```text
date,ticker,score,available_at
2024-01-02,NVDA,0.95,2024-01-02T20:00:00+00:00
```

## Implemented backtest formulas

### Forward return

```text
forward return = (next close / current close) - 1
```

### Portfolio return before costs

```text
gross portfolio return = sum(position weight × stock forward return)
```

The current demo assigns `+0.5` to the highest score and `-0.5` to the lowest score.

### Turnover and cost

```text
turnover = sum(abs(new weight - old weight))
trading cost = turnover × cost rate
net return = gross return - trading cost
```

### Rank IC

Rank IC asks whether higher scores line up with better later returns.

```text
rank IC = correlation(rank(scores), rank(forward returns))
```

`+1` means perfect ordering in a small sample, `0` means no ordering relationship, and `-1` means the ranking was exactly backwards. Real research needs many observations; one small sample proves nothing.

### Sharpe ratio and drawdown

```text
annualized Sharpe = sqrt(252) × average daily return / daily-return volatility
drawdown = portfolio value / previous peak value - 1
```

The synthetic demo's high Sharpe number is meaningless. It is a calculator check, not a strategy result.

## Supply-chain scenario calculations

The scenario engine is separate from factor scoring. It estimates exposure to a hypothetical disruption; it does not predict a stock return.

Each directed relationship has:

- `weight`: dependency strength, from 0 (weak) to 1 (strong).
- `substitutability`: how easy it is to replace the source, from 0 (very hard) to 1 (easy).
- `confidence`: how reliable the relationship evidence and current assumptions are.
- `effective_from` / `effective_to`: when the relationship is considered applicable.
- `source_url`: evidence location that should be reviewed and maintained.

For an incoming disruption severity `s`:

```text
propagated exposure = s × weight × (1 - substitutability)
```

For example, a TSMC disruption severity of `0.90` flowing to Nvidia over a `0.95` weight with `0.05` substitutability is:

```text
0.90 × 0.95 × (1 - 0.05) = 0.81225
```

This is an exposure score, not a forecast that Nvidia's price moves by 81%.

Confidence is reported separately. Along a multi-step path it is multiplied, so each additional unverified relationship lowers our confidence in the full explanation.

## Mapping a complex industry

The semiconductor industry cannot be represented as a single supplier-to-customer map. We will use typed, effective-dated relationships:

| Relationship type | Example | Scenario behavior |
|---|---|---|
| Supplier to customer | TSMC to Nvidia | Supply disruption can harm the customer. |
| Equipment to manufacturer | ASML to TSMC | Equipment constraints can reduce capacity. |
| Competitor | TSMC and Samsung Foundry | One firm's disruption may create an opportunity for the other. |
| License or IP | ARM to Qualcomm | Can affect development or product capability. |
| Customer concentration | Nvidia to cloud providers | Can pass supply limitations downstream. |
| Regulation/geography | Export rule affecting several firms | Can affect multiple entities without a supply edge. |

We will not make one shock-propagation formula cover every relationship. Each type needs its own documented behavior and evidence. The current tool supports the first deterministic dependency form only. Later work will add richer relation types, historical validation, and only then test a graph neural network.

## Implemented versus planned

| Capability | Status |
|---|---|
| Frozen-data backtest and future-data rejection | Implemented |
| Synthetic demo factors and prices | Implemented |
| Deterministic supply-chain dependency scenarios | Implemented |
| SEC filing ingestion and filing-language score | Planned next |
| Walk-forward validation and false-discovery controls | Planned |
| Graph neural network | Later research experiment |
| LLM hypothesis generation | Later, after the evaluator is trusted |
| Live trading | Explicitly out of scope for the MVP |
