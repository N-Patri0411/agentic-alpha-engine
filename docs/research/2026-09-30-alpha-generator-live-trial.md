# 2026-09-30 Alpha Generator Luna trial

## Scope

This was a bounded manual trial of the configured Alpha Generator role using
Luna. It used the repository's hand-authored demo factors and prices and was a
paper-research workflow only; it was not a production or investment run.

## Outcome

The first configured call returned candidate objects with incompatible field
names. The local schema validator rejected all candidates before any formula
could reach evaluation. The generator prompt and compatibility handling were
then repaired to require `id`, `expression`, and `rationale` fields.

The second call produced the bounded candidate `Rank(score)`. It generated 12
scored rows and was evaluated across three backtest periods. The Gatekeeper
rejected the candidate because the trial had fewer than 20 periods and no
out-of-sample segment. No paper portfolio was created.

The local ignored receipt is
`reports/live-luna-alpha-retry-2026-09-30.json`, with receipt SHA-256:

`77989ea2721706c3670aee6ef73dadd77e3e14e6895f19f978b2d4931b0f4dee`

No raw provider output or credentials are retained in this note.

## Interpretation

The run validates the bounded schema, provenance, evaluation, and gatekeeping
plumbing only. Because the inputs were hand-authored demo factors and prices,
the result provides no evidence of alpha, predictive validity, or investability.
