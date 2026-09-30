from datetime import UTC, datetime, timedelta

import pytest

from alpha_workbench.agents.contracts import (
    AgentRequest,
    MonitorEvaluationRequest,
    MonitorPolicy,
    SignalMetricObservation,
)
from alpha_workbench.agents.monitor import MonitorAgent

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def observations(
    count: int = 20,
    *,
    old_ic: float = 0.15,
    new_ic: float = 0.15,
    old_return: float = 0.01,
    new_return: float = 0.01,
    correlation: float | None = 0.20,
    available_lag_days: int = 0,
) -> list[SignalMetricObservation]:
    rows: list[SignalMetricObservation] = []
    for index in range(count):
        period = BASE + timedelta(days=index)
        rows.append(
            SignalMetricObservation(
                as_of_time=period,
                available_at=period + timedelta(days=available_lag_days),
                rank_ic=old_ic if index < count // 2 else new_ic,
                net_return=old_return if index < count // 2 else new_return,
                correlation_to_library=correlation,
            )
        )
    return rows


def request(rows: list[SignalMetricObservation], *, as_of: datetime | None = None):
    cutoff = as_of or BASE + timedelta(days=len(rows) - 1)
    return MonitorEvaluationRequest(
        hypothesis_id="graph-risk-v1",
        as_of_time=cutoff,
        measured_at=cutoff + timedelta(hours=1),
        observations=rows,
        policy=MonitorPolicy(min_observations=20, rolling_window=20),
    )


def test_healthy_signal_has_no_gatekeeper_event() -> None:
    result = MonitorAgent().evaluate(request(observations()))

    assert result.status == "healthy"
    assert result.health.status == "active"
    assert result.health.rolling_rank_ic == pytest.approx(0.15)
    assert result.health.quality_drift == pytest.approx(0.0)
    assert result.review_event is None


def test_quality_decay_requests_gatekeeper_review_without_retiring_signal() -> None:
    result = MonitorAgent().evaluate(
        request(observations(old_ic=0.30, new_ic=-0.10, old_return=0.02, new_return=-0.02))
    )

    assert result.status == "needs_review"
    assert result.health.status == "watch"
    assert result.review_event is not None
    assert result.review_event.trigger == "decay"
    assert result.review_event.source_agent == "monitor"
    assert result.review_event.health.status == "watch"


def test_stale_data_requests_review_and_preserves_measured_metrics() -> None:
    cutoff = BASE + timedelta(days=30)
    result = MonitorAgent().evaluate(request(observations(), as_of=cutoff))

    assert result.status == "needs_review"
    assert result.review_event is not None
    assert result.review_event.trigger == "stale_data"
    assert result.health.rolling_net_return == pytest.approx(0.01)
    assert result.health.freshness_age_days == pytest.approx(11.0)


def test_crowding_is_a_review_event_when_quality_is_still_healthy() -> None:
    result = MonitorAgent().evaluate(request(observations(correlation=0.95)))

    assert result.status == "needs_review"
    assert result.review_event is not None
    assert result.review_event.trigger == "crowding"
    assert "correlation" in result.review_event.reasons[0]


def test_insufficient_history_requests_replacement_review() -> None:
    result = MonitorAgent().evaluate(
        request(observations(count=3), as_of=BASE + timedelta(days=2))
    )

    assert result.status == "insufficient_data"
    assert result.health.rolling_rank_ic is None
    assert result.review_event is not None
    assert result.review_event.trigger == "replacement_needed"


def test_future_evidence_is_rejected_by_point_in_time_guard() -> None:
    rows = observations()
    rows[-1] = rows[-1].model_copy(update={"available_at": BASE + timedelta(days=21)})

    with pytest.raises(ValueError, match="available_at"):
        MonitorAgent().evaluate(request(rows))


def test_malformed_duplicate_or_timezone_less_observation_is_rejected() -> None:
    rows = observations()
    rows[1] = rows[0]
    with pytest.raises(ValueError, match="duplicate"):
        MonitorAgent().evaluate(request(rows))

    naive = observations()
    naive[0] = naive[0].model_copy(update={"as_of_time": datetime(2026, 1, 1)})
    with pytest.raises(ValueError, match="timezone"):
        MonitorAgent().evaluate(request(naive))


def test_a2a_run_returns_typed_json_and_does_not_write_library() -> None:
    monitor_request = request(observations())
    result = MonitorAgent().run(
        AgentRequest(
            run_id="monitor-test",
            agent="monitor",
            payload=monitor_request.model_dump(mode="json"),
        )
    )

    assert result.status == "completed"
    assert '"status": "healthy"' in result.message
