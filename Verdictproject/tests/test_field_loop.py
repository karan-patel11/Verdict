"""Loop A (field extraction) — the guaranteed loop and the forecast path.

Asserts the property the whole project turns on: on a non-exchangeable stream, the ACI-adapted
field loop holds its MARGINAL miscoverage guarantee (auto-and-wrong / all fields ≤ α) across
the shift — first half ≈ last half ≈ α — and its AutomationForecast holds (not logged as a
failure). Also checks the fault-tolerance and path contracts the loop must honor.
"""
from __future__ import annotations

import random

import pytest

from abstention.data.synthetic import SyntheticStream, StreamConfig
from abstention.deferral.reviewer_model import ReviewerAccuracyModel
from abstention.domain.taxonomy import RouteReason
from abstention.domain.types import BusinessAgeBucket, FieldType, Segment
from abstention.loops.field_loop import FieldInput, FieldLoop, FieldLoopConfig

SEG = Segment(industry_naics2="72", geography_state="CA", business_age=BusinessAgeBucket.LT_2Y)


def _loop(alpha=0.05, gamma=0.02, audit_rate=1.0):
    rm = ReviewerAccuracyModel(accuracy_by_field={}, default_accuracy=0.70)
    return FieldLoop(
        FieldLoopConfig(r_star=alpha, alpha=alpha, gamma=gamma, min_calibration=100,
                        quantile_window=800, audit_rate=audit_rate),
        rm,
        random.Random(0),
    )


def _inputs(labeled):
    return [
        FieldInput(field_type=f.field_type, calibrated_confidence=f.confidence,
                   true_error=f.true_error, segment=SEG)
        for f in labeled
    ]


def _run_stream(loop, seed=3, n_cases=2200, batch=300):
    fields = SyntheticStream(
        StreamConfig(seed=seed, n_cases=n_cases, exchangeable=False, drift_strength=0.6,
                     industry_cluster_length=45, campaign_burst_prob=0.06, ood_error_gain=0.07)
    ).field_stream()
    batches = [fields[i : i + batch] for i in range(0, len(fields) - batch, batch)]
    return [loop.process_batch(f"b{i}", _inputs(ch), segment=SEG) for i, ch in enumerate(batches)]


def test_aci_holds_marginal_miscoverage_guarantee_across_the_shift():
    loop = _loop(alpha=0.05)
    results = _run_stream(loop)
    miscov = [r.realized_marginal_miscoverage for r in results]
    h = len(miscov) // 2
    overall = sum(miscov) / len(miscov)
    first = sum(miscov[:h]) / h
    last = sum(miscov[h:]) / (len(miscov) - h)

    # Distribution-free marginal guarantee: realized ≈ α, and it does NOT drift up over the
    # second (heavily shifted) half of the stream.
    assert overall == pytest.approx(0.05, abs=0.02)
    assert last <= 0.05 + 0.02
    assert abs(last - first) < 0.03  # the shift does not break the guarantee


def test_automation_forecast_is_emitted_and_holds():
    loop = _loop(alpha=0.05)
    results = _run_stream(loop)
    # Warm-up batches (no calibration yet) automate nothing; steady-state batches carry a
    # real forecast that is honest (predicted automation matches realized) and not a failure.
    steady = [r for r in results if r.forecast.threshold_tau > 0.0]
    assert steady, "expected steady-state batches with a positive threshold"
    for r in steady:
        # The forecast is emitted in advance and its automation prediction is exact within the
        # batch (τ is frozen for the batch), so it is never a forecast miss.
        assert not r.forecast_score.automation_missed
    failures = [r for r in steady if r.forecast_score.is_failure]
    assert len(failures) / len(steady) < 0.2  # the guarantee holds on the vast majority


def test_no_confidence_routes_and_is_excluded_from_calibration():
    loop = _loop()
    batch = [
        FieldInput(FieldType.GROSS_REVENUE, calibrated_confidence=None, true_error=0, segment=SEG),
        FieldInput(FieldType.NET_INCOME, calibrated_confidence=0.95, true_error=0, segment=SEG),
    ]
    scores_before = len(loop._scores)
    result = loop.process_batch("b", batch, segment=SEG)
    degraded = [r for r in result.records if r.path == "DEGRADED"]
    assert len(degraded) == 1
    assert degraded[0].reason is RouteReason.NO_CONFIDENCE_AVAILABLE
    assert degraded[0].action.name == "ROUTE"
    assert result.n_degraded == 1
    # The degraded item must not have entered the conformity distribution (would corrupt α_t).
    assert len(loop._scores) - scores_before <= 1  # only the confident item's score, not the None


def test_forced_paths_always_route():
    loop = _loop()
    batch = [
        FieldInput(FieldType.DEPRECIATION, 0.99, 0, SEG, forced_path="PATH_1",
                   absent_reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT),
        FieldInput(FieldType.GROSS_REVENUE, 0.99, 0, SEG, forced_path="PATH_3"),
    ]
    result = loop.process_batch("b", batch, segment=SEG)
    paths = {r.path: r for r in result.records}
    assert paths["PATH_1"].action.name == "ROUTE"
    assert paths["PATH_1"].reason is RouteReason.FIELD_ABSENT_FROM_DOCUMENT
    assert paths["PATH_3"].action.name == "ROUTE"
    assert paths["PATH_3"].reason is RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT
    # Path 3 routed at confidence 0.99 — confidence is irrelevant to it.
    assert result.n_automated == 0
