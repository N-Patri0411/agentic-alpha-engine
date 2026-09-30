# Gatekeeper and paper portfolio policy — 2026-09-30

The gatekeeper is a deterministic research-quality check. It requires a
minimum history, positive transaction-cost coverage, a drawdown within the
configured limit, and both baseline and out-of-sample reports. Missing
baseline or out-of-sample evidence produces `needs_review`; failed numeric
checks produce `rejected`. A passing decision is only a research decision and
does not promote a hypothesis or imply that an alpha exists.

The portfolio optimiser consumes an accepted `GateDecision` and finite ticker
scores to produce bounded, equal-weight long/short paper targets. Rejected and
review decisions always produce zero targets. The implementation has no
broker, order, account, or execution interface by design.
