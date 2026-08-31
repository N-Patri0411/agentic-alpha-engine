# Verified demo results

These are repeatable, synthetic demonstrations of the current Sprint 1 code.
They demonstrate that the software calculations and point-in-time safeguards
work. They are **not** evidence that any investment strategy will make money.

## How to replay

After setup, double-click `run-demos.cmd` in the repository root. It runs a
synthetic long/short factor backtest, a 90% TSMC disruption scenario, and a 70%
ASML disruption scenario.

## Current output

### Synthetic factor backtest

The frozen demonstration data has three rebalance periods and deliberately
aligns the factor with following price movement. The resulting metrics are
intentionally extreme: annualized Sharpe `96.78`, mean rank IC `0.9658`, and
net return `0.05059` across three periods.

This is a plumbing test, not a research result. Real evaluation needs much more
history, realistic point-in-time data, locked out-of-sample periods, and
comparison against simple baselines.

### TSMC disruption scenario

With a starting disruption severity of `0.90` at TSMC, the illustrative graph
currently reports these downstream exposures:

| Entity | Scenario exposure |
| --- | ---: |
| NVIDIA | 0.81225 |
| AMD | 0.74520 |
| Microsoft | 0.38988 |

### ASML disruption scenario

With a starting disruption severity of `0.70` at ASML, the illustrative graph
currently reports:

| Entity | Scenario exposure |
| --- | ---: |
| TSMC | 0.65170 |
| NVIDIA | 0.58816 |
| AMD | 0.53961 |
| Microsoft | 0.28232 |

The values above are outputs of handwritten placeholder relationships. They are
not price forecasts, factor values, or trading instructions. The next domain
mapping slice replaces placeholders with evidence-backed, effective-dated
relationships and deliberately records uncertainty where public evidence is
weak.
