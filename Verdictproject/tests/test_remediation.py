"""Falsifying tests for the six audit failures (F1–F6) plus the V6 mechanism guard.

Each test (except test_v6_mechanism_holds, which is a REGRESSION GUARD and passes now)
is written to FAIL against current source and to pass only once the corresponding fix
lands. The failure mode each catches is documented inline.

Run order mirrors the remediation loop. These are intentionally strict: a version that
passes at a token residual / a smuggled second threshold is the defect in disguise.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import pytest
import yaml

from abstention.experiment.report import build_report

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def _cfg():
    return yaml.safe_load((CONFIGS / "shift_severe.yaml").read_text())


@pytest.fixture(scope="module")
def report():
    return build_report(CONFIGS / "shift_severe.yaml")


# =====================================================================================
# F1 — one goalpost, one metric: conditional selective risk R(f,g)=E[ℓg]/φ at one r*
#      (Geifman 2017 Eq. 1). Fails now: report scores the system on MARGINAL miscoverage
#      at α=0.10 and the naive on conditional risk at r*=0.05 — two metrics, two
#      thresholds. There is no single-metric, single-r* comparison object.
# =====================================================================================
def test_common_threshold_comparison(report):
    comp = report["claim"].get("comparison")
    assert comp is not None, "no single-metric/single-r* comparison object exists (F1 defect)"
    # ONE metric for BOTH rules: conditional selective risk (denominator = coverage).
    assert comp["metric"] == "conditional_selective_risk"
    # ONE threshold for BOTH rules.
    rstar = comp["r_star"]
    assert comp["system_r_star"] == rstar
    assert comp["naive_r_star"] == rstar
    # Both rules' numbers present and scored at that shared r* on that shared metric.
    assert "system_conditional_selective_risk" in comp
    assert "naive_violation_rate" in comp
    # No smuggled marginal-vs-conditional or α-vs-r* mismatch anywhere in the comparison.
    assert "marginal" not in comp["metric"]
    assert comp["system_r_star"] != report["meta"].get("alpha") or rstar == report["meta"]["alpha"], \
        "system must be evaluated at r*, not silently at α"


# =====================================================================================
# F2 — the forecast must be a real held-out prediction (Gibbs 2021 §2: threshold fit on
#      {1..t-1}, err_t scored on the unseen (X_t,Y_t)). Fails now: forecast() and
#      process_batch() apply the same frozen τ to the same rows ⇒ predicted ≡ realized
#      automation in every batch (auto_err identically 0), so automation_missed can never
#      fire and "0 failures" is vacuous.
# =====================================================================================
def test_forecast_can_miss(report):
    batches = report["forecast"]["batches"]
    auto_errs = [abs(b["predicted_automation_rate"] - b["realized_automation_rate"]) for b in batches]
    # The core falsifier: a genuine forecast MUST be capable of missing.
    assert max(auto_errs) > 0.0, (
        "predicted_automation ≡ realized_automation in every batch — forecast recomputes "
        "the same rows it is scored on (F2 defect)"
    )
    # And the miss must be non-token: a real held-out forecast under shift misses materially
    # on a meaningful fraction of batches, not one lucky row.
    material = sum(1 for e in auto_errs if e > 0.01)
    assert material >= max(1, len(batches) // 4), (
        f"only {material}/{len(batches)} batches show a real held-out miss"
    )


# =====================================================================================
# F3 — decouple true_error from the scored confidence (Kamath 2020 §1/§5: softmax is a
#      strong but PARTIAL, OOD-overconfident predictor). Fails now: true_error ~
#      Bernoulli(0.50 − 0.55·conf + 0.07·(1−φ)) — a near-deterministic function of the
#      scored confidence, with no latent residual. The residual gap at fixed confidence
#      must exceed a real floor (0.15), not 1e-6.
# =====================================================================================
def test_confidence_not_definitional():
    from abstention.data.synthetic import StreamConfig, SyntheticStream, stream_config_from_mapping

    # (a) The residual is a real, tunable knob whose default sits well below 1.0.
    assert "confidence_truth_corr" in StreamConfig.__dataclass_fields__, \
        "no confidence↔truth correlation knob exists (confidence is definitional)"
    default_corr = StreamConfig.__dataclass_fields__["confidence_truth_corr"].default
    assert 0.6 <= default_corr <= 0.75, f"default corr {default_corr} must be a partial predictor"

    # (b) At (near-)identical confidence, P(error) must differ MATERIALLY across the latent.
    cfg = _cfg()
    cfg["stream"] = {**cfg["stream"], "n_cases": 6000}
    fields = SyntheticStream(stream_config_from_mapping(cfg, seed=1)).field_stream()
    assert hasattr(fields[0], "latent_correctness"), \
        "no latent correctness factor is exposed as ground truth"
    band = [f for f in fields if 0.78 <= f.confidence <= 0.82]
    assert len(band) >= 800, f"too few fields in the fixed-confidence band ({len(band)})"
    band.sort(key=lambda f: f.latent_correctness)
    k = len(band) // 3
    low, high = band[:k], band[-k:]
    err_low = sum(f.true_error for f in low) / len(low)
    err_high = sum(f.true_error for f in high) / len(high)
    residual_gap = err_low - err_high
    assert residual_gap > 0.15, (
        f"confidence is near-definitional: at fixed confidence the low/high-latent error-rate "
        f"gap is only {residual_gap:.3f} (need > 0.15)"
    )


# =====================================================================================
# F4 (branch b — DECLARED) — the "calibrated" label must be HONEST. On this decoupled
#      synthetic data the RF calibrator does NOT beat raw softmax on risk–coverage AUC
#      (measured), so it is OFF-PATH: routing uses raw extractor softmax and no surface calls
#      the raw value "calibrated". The AUC evidence is recorded so the branch is auditable
#      and re-decides automatically if a real corpus makes the calibrator win.
#      Fails now: build_report records no calibrator status, and graph surfaces label the raw
#      softmax as "calibrated". (Was test_calibrated_confidence_is_calibrated.)
# =====================================================================================
def test_confidence_label_is_honest(report):
    cal = report["meta"].get("calibrator")
    assert cal is not None, "no calibrator status recorded — off-path but unlabelled (F4 defect)"
    assert "aurc_raw" in cal and "aurc_calibrator" in cal, "no AUC evidence recorded"
    # The label must match the measured reality, whichever way the AUC falls.
    if cal["on_path"]:
        assert cal["aurc_calibrator"] < cal["aurc_raw"], "on-path claimed but calibrator loses AUC"
        assert cal["routing_signal"] == "kamath_calibrator_output"
    else:
        assert cal["aurc_raw"] <= cal["aurc_calibrator"], "off-path claimed but calibrator wins AUC"
        assert cal["routing_signal"] == "raw_extractor_softmax"
    # No graph surface may call the RAW softmax value "calibrated confidence".
    for a in report["analyses"]:
        if not a["graph"]:
            continue
        for n in a["graph"]["nodes"]:
            assert "calibrated confidence" not in (n.get("description", "") or "").lower(), (
                f"node {n['id']} still calls raw softmax 'calibrated confidence' (F4 defect)"
            )


# =====================================================================================
# F5 — no surface may imply control the system does not exercise (chosen path: DELETE).
#      Fails now: ReviewerBudget.can_route() is defined but never called, and two
#      RouteReason members are defined but never emitted.
# =====================================================================================
def test_no_dead_control():
    from abstention.deferral.budget import ReviewerBudget
    from abstention.domain.taxonomy import RouteReason

    assert not hasattr(ReviewerBudget, "can_route"), \
        "can_route() is a defined-but-never-called control surface (F5 defect)"
    names = {r.name for r in RouteReason}
    assert "REVIEWER_BUDGET_FORCES_CONSERVATIVE_ROUTE" not in names, \
        "unemitted reason code still present (F5 defect)"
    assert "SEGMENT_COVERAGE_BELOW_TARGET" not in names, \
        "unemitted reason code still present (F5 defect)"


# =====================================================================================
# F6 — the memory layer must REJECT an accepted contradiction, not silently drop it.
#      Fails now: build_file_graph trusts its caller; a PATH_3 outcome with decision=
#      "ACCEPT" produces no finding and no error (a silent invariant hole).
# =====================================================================================
def test_memory_layer_rejects_accepted_contradiction():
    from abstention.memory import build_file_graph, AnalysisStatus, FieldOutcome, SourceRef
    from abstention.domain.taxonomy import RouteReason
    from abstention.domain.types import FieldType

    bad = FieldOutcome(
        index=0, field_type=FieldType.COGS, path="PATH_3", decision="ACCEPT",
        reason=RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT,
        source=SourceRef("d1", "BALANCE_SHEET", 2, (0.1, 0.2, 0.3, 0.4), "5"),
        confidence=0.99, reviewer_accuracy=0.7, ood_score=0.1, tau=0.25,
        conflict_source=SourceRef("d2", "PROFIT_AND_LOSS", 1, (0.1, 0.2, 0.3, 0.4), "9999"),
    )
    with pytest.raises((ValueError, Exception)) as ei:
        build_file_graph(analysis_id="an-x", file_label="x.bundle", outcomes=[bad],
                         status=AnalysisStatus.COMPLETED, generated_at="t")
    assert "contradict" in str(ei.value).lower() or "PATH_3" in str(ei.value) or "accept" in str(ei.value).lower()


# =====================================================================================
# V6 (reinterpreted) — REGRESSION GUARD, not a red test.
#   V6 is the MECHANISM (ACI drives marginal miscoverage toward α over the stream), NOT
#   the literal 6.2%. This test PASSES on current source by design; its job is to go RED
#   only if a later fix breaks the ACI mechanism. After F3, the honest miscoverage may
#   rise — that is CORRECT and must NOT be hidden by widening slack, relaxing α, or
#   shortening the horizon. If ACI can no longer reach a controlled regime at all, this
#   test fails → STOP and report (do not tune the generator to rescue 6.2%).
# =====================================================================================
def test_v6_mechanism_holds(report):
    from abstention.conformal.aci import ACIState, prop41_coverage_bound

    alpha = report["meta"]["alpha"]
    batches = report["forecast"]["batches"]

    # (1) ACI is actually adapting: α_t is not frozen.
    alpha_ts = [round(b["alpha_t"], 4) for b in batches]
    assert len(set(alpha_ts)) > 1, "α_t is constant — ACI is not adapting (mechanism dead)"

    # (2) Negative-feedback sign (Gibbs Eq. 2): a high-error step lowers the next α_t.
    #     Deterministic unit check, independent of the report's realized numbers.
    s = ACIState(alpha_target=alpha, gamma=0.02)
    after_miss = s.update(err=1).alpha
    after_cover = s.update(err=0).alpha
    assert after_miss < s.alpha < after_cover, "ACI feedback sign is wrong (Eq. 2 broken)"

    # (3) The regime is CONTROLLED, not diverging. Wide envelope: catches 'ACI can no longer
    #     reach α' (the STOP condition) without pinning the honest number. NOT an equality,
    #     NOT the 6.2% figure.
    miscov = report["claim"]["system_overall_marginal_miscoverage"]
    assert miscov <= 2 * alpha, (
        f"marginal miscoverage {miscov:.3f} diverged past a controlled regime (> 2α) — "
        "report as a real finding, do not tune to hide it"
    )
    # Sanity that the distribution-free envelope is even meaningful at this horizon.
    T = report["meta"]["n_fields"]
    assert prop41_coverage_bound(alpha, 0.02, T) < alpha
