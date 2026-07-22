"""AutomationForecast — the "in advance" claim as a first-class object (Part 0).

The system must forecast its own automation rate BEFORE processing a batch, and the forecast
must hold. This is not a metric computed afterward: AutomationForecast is emitted per batch and
per segment, then scored against the realized automation rate and selective risk. A forecast
that misses is a SYSTEM FAILURE logged as such (ForecastScore.is_failure), not a row in a table.

"Holds" means two things: the realized selective risk does not exceed the guaranteed target r*
(the guarantee), and the realized automation rate lands within tolerance of the prediction (the
forecast was honest). Either failure flips is_failure.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.types import Segment


@dataclass(frozen=True, slots=True)
class AutomationForecast:
    """Emitted BEFORE a batch is processed, from pre-observation information only (features →
    calibrated confidence → the current ACI-adapted threshold). segment=None is the overall
    batch forecast; a per-segment forecast carries its Segment.

    The GUARANTEED quantity is target_marginal_miscoverage: the fraction of ALL fields that are
    confidently automated yet wrong, which ACI holds ≤ α distribution-free (Gibbs Prop 4.1).
    This is MARGINAL, not conditional (non-goal: "ACI gives marginal"). The conditional
    selective risk — error rate among automated fields — is instrumented and surfaced per
    segment (telemetry), never claimed as guaranteed."""

    batch_id: str
    segment: Segment | None
    n_fields: int
    predicted_automation_rate: float  # fraction of fields expected to be automated (accepted)
    target_marginal_miscoverage: float  # α — the ACI-guaranteed cap on auto-and-wrong / total
    predicted_coverage: float  # 1 − α, the ACI marginal-coverage target on the field layer
    threshold_tau: float  # the ACI-adapted nonconformity threshold used to predict
    method: str = "aci_calibrated"


@dataclass(frozen=True, slots=True)
class ForecastScore:
    forecast: AutomationForecast
    realized_automation_rate: float
    realized_marginal_miscoverage: float  # auto-and-wrong / all fields — the GUARANTEED quantity
    realized_conditional_selective_risk: float  # auto-and-wrong / automated — reported, not guaranteed
    realized_coverage: float
    n_observed_accepts: int
    automation_abs_error: float
    guarantee_exceeded: bool  # realized marginal miscoverage > α — the guarantee missed
    automation_missed: bool  # |predicted − realized| beyond tolerance — the forecast missed
    is_failure: bool


def score_forecast(
    forecast: AutomationForecast,
    realized_automation_rate: float,
    realized_marginal_miscoverage: float,
    realized_conditional_selective_risk: float,
    realized_coverage: float,
    n_observed_accepts: int,
    automation_tolerance: float = 0.10,
    miscoverage_slack: float = 0.02,
) -> ForecastScore:
    """Score a forecast. is_failure iff the ACI guarantee was missed (marginal miscoverage >
    α + slack) OR the automation-rate prediction missed by more than automation_tolerance. The
    slack absorbs finite-batch sampling noise; the distribution-free bound is asymptotic."""
    auto_err = abs(forecast.predicted_automation_rate - realized_automation_rate)
    guarantee_exceeded = realized_marginal_miscoverage > forecast.target_marginal_miscoverage + miscoverage_slack
    automation_missed = auto_err > automation_tolerance
    return ForecastScore(
        forecast=forecast,
        realized_automation_rate=realized_automation_rate,
        realized_marginal_miscoverage=realized_marginal_miscoverage,
        realized_conditional_selective_risk=realized_conditional_selective_risk,
        realized_coverage=realized_coverage,
        n_observed_accepts=n_observed_accepts,
        automation_abs_error=auto_err,
        guarantee_exceeded=guarantee_exceeded,
        automation_missed=automation_missed,
        is_failure=guarantee_exceeded or automation_missed,
    )
