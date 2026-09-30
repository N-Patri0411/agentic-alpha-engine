"""Deterministic signal-health monitoring and Gatekeeper review handoff."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from statistics import fmean
from time import perf_counter
from typing import Literal

from pydantic import ValidationError

from .base import SkeletonAgent
from .contracts import (
    AgentRequest,
    AgentResult,
    GatekeeperReviewEvent,
    MonitorEvaluationRequest,
    MonitorEvaluationResult,
    MonitorPolicy,
    SignalHealthSnapshot,
    SignalMetricObservation,
)

ReviewTrigger = Literal["decay", "stale_data", "crowding", "replacement_needed"]


class MonitorAgent(SkeletonAgent):
    """Measure realised signal health and request, but never perform, retirement.

    The Monitor consumes metrics already calculated by the research layer. It
    applies explicit thresholds, checks chronology, and emits a typed event for
    Gatekeeper when quality, freshness, or crowding needs review. It has no
    model, graph, or signal-library write access.
    """

    name = "monitor"

    def evaluate(self, request: MonitorEvaluationRequest) -> MonitorEvaluationResult:
        """Evaluate a signal at ``request.as_of_time`` with no side effects."""

        as_of = _aware(request.as_of_time, "as_of_time")
        measured_at = _aware(request.measured_at, "measured_at")
        if measured_at < as_of:
            raise ValueError("measured_at cannot be earlier than as_of_time")

        observations = _validate_and_sort_observations(request.observations, as_of)
        policy = request.policy
        if len(observations) < policy.min_observations:
            health = SignalHealthSnapshot(
                hypothesis_id=request.hypothesis_id,
                measured_at=measured_at,
                observation_count=len(observations),
                status="watch",
            )
            reason = (
                f"insufficient observations: {len(observations)} < "
                f"{policy.min_observations}"
            )
            event = _review_event(
                request, health, "replacement_needed", [reason], as_of, measured_at
            )
            return MonitorEvaluationResult(
                hypothesis_id=request.hypothesis_id,
                as_of_time=as_of,
                measured_at=measured_at,
                status="insufficient_data",
                health=health,
                reasons=[reason],
                review_event=event,
            )

        window = observations[-policy.rolling_window :]
        ic_values = [row.rank_ic for row in window if row.rank_ic is not None]
        return_values = [row.net_return for row in window if row.net_return is not None]
        correlations = [
            row.correlation_to_library
            for row in window
            if row.correlation_to_library is not None
        ]
        if not ic_values and not return_values:
            raise ValueError("observations contain neither rank_ic nor net_return metrics")

        rolling_ic = _mean_or_none(ic_values)
        rolling_return = _mean_or_none(return_values)
        correlation = _mean_or_none(correlations)
        quality_drift, decay_score = _quality_drift(window)
        latest_period = max(_aware(row.as_of_time, "observation.as_of_time") for row in window)
        latest_input = request.latest_input_available_at
        if latest_input is not None:
            latest_input = _aware(latest_input, "latest_input_available_at")
            if latest_input > as_of:
                raise ValueError("latest_input_available_at cannot be after as_of_time")
        latest_known = max(
            latest_period,
            max(_aware(row.available_at, "observation.available_at") for row in window),
            *(latest_input,) if latest_input is not None else (),
        )
        freshness_age_days = max(0.0, (as_of - latest_known).total_seconds() / 86_400)

        reasons: list[str] = []
        trigger: ReviewTrigger | None = None
        if freshness_age_days > policy.stale_after_days:
            trigger = "stale_data"
            reasons.append(
                f"latest usable signal input is {freshness_age_days:.2f} days old "
                f"(limit {policy.stale_after_days:g})"
            )
        if _is_decay(window, rolling_ic, rolling_return, quality_drift, policy):
            trigger = "decay"
            reasons.append("recent realised quality has decayed beyond the configured threshold")
        if correlation is not None and correlation >= policy.crowding_correlation_threshold:
            if trigger is None:
                trigger = "crowding"
            reasons.append(
                f"mean library correlation {correlation:.3f} is at or above "
                f"{policy.crowding_correlation_threshold:g}"
            )

        status: Literal["active", "watch"] = "watch" if trigger is not None else "active"
        health = SignalHealthSnapshot(
            hypothesis_id=request.hypothesis_id,
            measured_at=measured_at,
            observation_count=len(observations),
            rolling_rank_ic=rolling_ic,
            rolling_net_return=rolling_return,
            correlation_to_library=correlation,
            quality_drift=quality_drift,
            decay_score=decay_score,
            freshness_age_days=freshness_age_days,
            status=status,
        )
        review = (
            _review_event(request, health, trigger, reasons, as_of, measured_at)
            if trigger is not None
            else None
        )
        return MonitorEvaluationResult(
            hypothesis_id=request.hypothesis_id,
            as_of_time=as_of,
            measured_at=measured_at,
            status="needs_review" if review is not None else "healthy",
            health=health,
            reasons=reasons,
            review_event=review,
        )

    def run(self, request: AgentRequest) -> AgentResult:
        """Evaluate an A2A request and serialize the typed result."""

        if request.agent != self.name:
            raise ValueError(f"{self.name} cannot handle a {request.agent} request")
        started = perf_counter()
        if not request.payload:
            return super().run(request)
        try:
            result = self.evaluate(MonitorEvaluationRequest.model_validate(request.payload))
            message = json.dumps(result.model_dump(mode="json"), sort_keys=True)
            status: Literal["completed", "failed"] = "completed"
        except (ValidationError, TypeError, ValueError) as exc:
            message = f"monitor evaluation failed: {exc}"
            status = "failed"
        return AgentResult(
            run_id=request.run_id,
            agent=self.name,
            status=status,
            message=message,
            latency_ms=int((perf_counter() - started) * 1000),
        )


def _validate_and_sort_observations(
    observations: list[SignalMetricObservation], as_of: datetime
) -> list[SignalMetricObservation]:
    checked: list[SignalMetricObservation] = []
    seen: set[datetime] = set()
    for row in observations:
        period = _aware(row.as_of_time, "observation.as_of_time")
        available = _aware(row.available_at, "observation.available_at")
        if period > as_of:
            raise ValueError("observation.as_of_time cannot be after as_of_time")
        if available > as_of:
            raise ValueError("observation.available_at cannot be after as_of_time")
        if period in seen:
            raise ValueError(f"duplicate observation period: {period.isoformat()}")
        if not any(value is not None for value in (row.rank_ic, row.net_return)):
            raise ValueError("each observation needs rank_ic or net_return")
        for value_name, value in (
            ("rank_ic", row.rank_ic),
            ("net_return", row.net_return),
            ("correlation_to_library", row.correlation_to_library),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{value_name} must be finite")
        seen.add(period)
        checked.append(row)
    return sorted(checked, key=lambda row: _aware(row.as_of_time, "observation.as_of_time"))


def _quality_drift(window: list[SignalMetricObservation]) -> tuple[float | None, float | None]:
    midpoint = len(window) // 2
    if midpoint < 2:
        return None, None
    prior_rows = window[:midpoint]
    recent_rows = window[midpoint:]
    prior_ic = [row.rank_ic for row in prior_rows if row.rank_ic is not None]
    recent_ic = [row.rank_ic for row in recent_rows if row.rank_ic is not None]
    if prior_ic and recent_ic:
        prior_quality = prior_ic
        recent_quality = recent_ic
    else:
        prior_quality = [row.net_return for row in prior_rows if row.net_return is not None]
        recent_quality = [row.net_return for row in recent_rows if row.net_return is not None]
    if not prior_quality or not recent_quality:
        return None, None
    drift = fmean(recent_quality) - fmean(prior_quality)
    decay_score = max(0.0, min(1.0, -drift / 0.10))
    return float(drift), float(decay_score)


def _is_decay(
    window: list[SignalMetricObservation],
    rolling_ic: float | None,
    rolling_return: float | None,
    quality_drift: float | None,
    policy: MonitorPolicy,
) -> bool:
    if rolling_ic is not None and rolling_ic < policy.negative_ic_threshold:
        return True
    if rolling_return is not None and rolling_return <= policy.negative_return_threshold:
        return True
    if quality_drift is not None and quality_drift <= -policy.decay_ic_delta:
        return True
    midpoint = len(window) // 2
    if midpoint >= 2:
        prior_returns = [row.net_return for row in window[:midpoint] if row.net_return is not None]
        recent_returns = [row.net_return for row in window[midpoint:] if row.net_return is not None]
        if prior_returns and recent_returns:
            return fmean(recent_returns) - fmean(prior_returns) <= -policy.decay_return_delta
    return False


def _review_event(
    request: MonitorEvaluationRequest,
    health: SignalHealthSnapshot,
    trigger: ReviewTrigger,
    reasons: list[str],
    as_of: datetime,
    measured_at: datetime,
) -> GatekeeperReviewEvent:
    fingerprint = json.dumps(
        {
            "hypothesis_id": request.hypothesis_id,
            "as_of_time": as_of.isoformat(),
            "trigger": trigger,
            "reasons": reasons,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    event_id = hashlib.sha256(fingerprint).hexdigest()[:24]
    return GatekeeperReviewEvent(
        event_id=event_id,
        hypothesis_id=request.hypothesis_id,
        trigger=trigger,
        as_of_time=as_of,
        measured_at=measured_at,
        reasons=reasons,
        health=health,
    )


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _mean_or_none(values: list[float]) -> float | None:
    return float(fmean(values)) if values else None
