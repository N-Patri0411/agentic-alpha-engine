# Monitor health-evaluation slice

The Monitor now consumes typed, already-realised signal metrics and evaluates
them using explicit deterministic thresholds. It measures rolling rank IC,
rolling net return, quality drift/decay, data freshness, and optional
correlation to the existing signal library.

Every metric carries an `as_of_time` and `available_at`. Future observations,
future availability timestamps, duplicate periods, timezone-less timestamps,
and non-finite values are rejected. This keeps monitoring consistent with the
research pipeline's point-in-time rules.

The output is a `SignalHealthSnapshot`. A healthy signal is marked `active`;
decay, stale inputs, crowding, or insufficient history are marked `watch` and
produce a typed `GatekeeperReviewEvent`. The event is only a review request:
the Monitor cannot retire a signal, change the signal library, or write graph
state. Gatekeeper remains the sole policy decision-maker.

This slice is deliberately standalone. It does not schedule runs or claim
economic validity. The next integration work is to feed retained rolling
backtest observations into the Monitor and route its review events through the
bounded Orchestrator/Gatekeeper workflow.
