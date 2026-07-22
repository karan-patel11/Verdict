"""One test per non-negotiable invariant (Part 3), named test_invariant_N_*.

TDD contract: invariants 1–10 exercise machinery built in steps 4–7. Until those modules
exist the imports fail and the tests are RED — that is the point. Invariants 11–12 are
domain-level and must be GREEN from step 3 onward.

Paper anchors below are the print-verified ones from GATE_REPORT.md.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from abstention.domain.models import (
    CalibratorFeatures,
    DecisionAction,
    ExtractedField,
    FieldDecision,
    Path1Absent,
    Path2Scored,
    Path3Contradicted,
    PathViolationError,
    Provenance,
)
from abstention.domain.taxonomy import (
    TAXONOMY_VERSION,
    AcceptReason,
    ReasonGroup,
    ROUTE_REASON_GROUP,
    RouteReason,
)
from abstention.domain.types import DocArchetype, FieldType


def _prov(doc="doc-1", page=1, span="1,234.00"):
    return Provenance(doc_id=doc, page=page, bbox=(0.1, 0.2, 0.3, 0.25), raw_span=span)


def _ext(ft=FieldType.GROSS_REVENUE, value="1234", conf=0.9, doc="doc-1"):
    return ExtractedField(
        field_type=ft, value=Decimal(value), provenance=_prov(doc=doc), raw_confidence=conf
    )


# ---------------------------------------------------------------------------------------
# Invariant 1 — selective risk uses the conditional denominator.
# Geifman & El-Yaniv 2017 §2, Eq. (1): R(f,g) = E[ℓ(f(x),y)g(x)] / φ(f,g), φ = E[g(x)].
# Routed items are NOT model errors.
# ---------------------------------------------------------------------------------------
def test_invariant_1_selective_risk_conditional_denominator():
    from abstention.conformal.sgr import empirical_coverage, empirical_selective_risk

    # 10 items; g accepts 4 of them; 1 error among accepted, 3 errors among routed.
    losses = [1, 0, 0, 0, 1, 1, 1, 0, 0, 0]
    accepted = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]

    phi = empirical_coverage(accepted)
    risk = empirical_selective_risk(losses, accepted)

    assert phi == pytest.approx(0.4)
    # Conditional denominator: 1 error / 4 accepted — NOT 4 errors / 10 items.
    assert risk == pytest.approx(1 / 4)


# ---------------------------------------------------------------------------------------
# Invariant 2 — conformity scores are scale-normalized at construction time.
# Gibbs & Candès 2021 §5: S_t = |V_t − σ̂²_t|/σ̂²_t is "critical for obtaining an
# approximately stationary conformity score"; raw |V_t − σ̂²_t| swings coverage ≈0.4–1.0.
# ---------------------------------------------------------------------------------------
def test_invariant_2_conformity_scores_scale_normalized_at_construction():
    from abstention.scoring.conformity import NormalizedConformityScorer

    with pytest.raises((TypeError, ValueError)):
        NormalizedConformityScorer(normalizer=None)  # raw absolute error is forbidden

    class UnitNormalizer:
        def scale(self, field_type, case_context):
            return Decimal("1000")

    scorer = NormalizedConformityScorer(normalizer=UnitNormalizer())
    s = scorer.score(
        field_type=FieldType.GROSS_REVENUE,
        predicted=Decimal("1200"),
        observed=Decimal("1000"),
        case_context=None,
    )
    assert s == pytest.approx(0.2)  # |1200−1000| / 1000, never the raw 200


# ---------------------------------------------------------------------------------------
# Invariant 3 — ACI update is exactly α_{t+1} = α_t + γ(α − err_t), γ default 0.005,
# clamped per Lemma 4.1 to [−γ, 1+γ] (NOT [0,1]). Gibbs & Candès Eq. (2), Lemma 4.1.
# No regret-bound machinery.
# ---------------------------------------------------------------------------------------
def test_invariant_3_aci_update_exact_and_clamped():
    from abstention.conformal.aci import ACIState

    st = ACIState(alpha_target=0.1)
    assert st.gamma == pytest.approx(0.005)

    st = st.update(err=1)
    assert st.alpha == pytest.approx(0.1 + 0.005 * (0.1 - 1))  # 0.0955
    st = st.update(err=0)
    assert st.alpha == pytest.approx(0.0955 + 0.005 * 0.1)  # 0.0960

    # Lemma 4.1 bounds: alpha_t ∈ [−γ, 1+γ] with probability one. The state must be
    # *provably inside* the lemma interval and must not clip to [0, 1].
    lo = ACIState(alpha_target=0.1, alpha=0.001)
    for _ in range(50):
        lo = lo.update(err=1)
    assert -lo.gamma <= lo.alpha <= 1 + lo.gamma
    assert lo.alpha < 0  # a [0,1] clip would silently break Lemma 4.1's dynamics

    hi = ACIState(alpha_target=0.9, alpha=0.999)
    for _ in range(50):
        hi = hi.update(err=0)
    assert -hi.gamma <= hi.alpha <= 1 + hi.gamma
    assert hi.alpha > 1


# ---------------------------------------------------------------------------------------
# Invariant 4 — no separate "OOD ⇒ escalate" branch. OOD-ness is a calibrator FEATURE.
# Kamath App. A.3: outlier detector AUC 24.23 > MaxProb 20.54 > calibrator 18.47 (lower
# is better) — routing on OOD is worse than doing nothing; OOD accuracy is 40–50%, not 0%.
# ---------------------------------------------------------------------------------------
def test_invariant_4_ood_is_a_feature_never_a_routing_trigger():
    # (a) The closed taxonomy has no OOD reason — an OOD branch would need one.
    assert not any("OOD" in r.name or "OUT_OF_D" in r.name for r in RouteReason)

    # (b) ood_score is present in the calibrator feature vector.
    feats = CalibratorFeatures(
        field_type=FieldType.GROSS_REVENUE,
        archetype=DocArchetype.BANK_STATEMENT,
        softmax_top5=(0.9, 0.05, 0.03, 0.01, 0.01),
        raw_span_length=8,
        doc_page_count=12,
        statement_transaction_count=240,
        distinct_source_documents=3,
        ood_score=0.97,
    )
    assert 0.97 in feats.to_vector()

    # (c) The router accepts a heavily-OOD item when calibrated confidence clears the
    # instance-conditional reviewer accuracy — OOD-ness alone must not route.
    from abstention.deferral.router import route_field

    decision = route_field(
        outcome=Path2Scored(
            field_type=FieldType.GROSS_REVENUE,
            extractions=(_ext(),),
            primary=_ext(),
            calibrated_confidence=0.99,
        ),
        features=feats,
        reviewer_accuracy=0.90,
    )
    assert decision.action is DecisionAction.ACCEPT


# ---------------------------------------------------------------------------------------
# Invariant 5 — Bayes-optimal deferral: defer iff calibrated confidence < expected
# reviewer accuracy, and reviewer accuracy is INSTANCE-DEPENDENT (per field_type,
# reviewer minimum). Mozannar & Sontag Prop. 2 / Eq. (5): r^B(x) = 1[max_y η_y(x) ≤
# P(Y=M|X=x)]. Constant reviewer accuracy is the §5.1 failure.
# ---------------------------------------------------------------------------------------
def test_invariant_5_deferral_compares_against_instance_reviewer_accuracy():
    from abstention.deferral.reviewer_model import ReviewerAccuracyModel
    from abstention.deferral.router import route_field

    model = ReviewerAccuracyModel(
        accuracy_by_field={
            (FieldType.NSF_COUNT, "rev-1"): 0.99,
            (FieldType.GROSS_REVENUE, "rev-1"): 0.80,
        }
    )
    # Same calibrated confidence, different instance ⇒ different decision.
    conf = 0.9
    o_nsf = Path2Scored(
        field_type=FieldType.NSF_COUNT,
        extractions=(_ext(ft=FieldType.NSF_COUNT, value="3"),),
        primary=_ext(ft=FieldType.NSF_COUNT, value="3"),
        calibrated_confidence=conf,
    )
    o_rev = Path2Scored(
        field_type=FieldType.GROSS_REVENUE,
        extractions=(_ext(),),
        primary=_ext(),
        calibrated_confidence=conf,
    )
    d_nsf = route_field(
        outcome=o_nsf, features=None,
        reviewer_accuracy=model.expected_accuracy(FieldType.NSF_COUNT, "rev-1"),
    )
    d_rev = route_field(
        outcome=o_rev, features=None,
        reviewer_accuracy=model.expected_accuracy(FieldType.GROSS_REVENUE, "rev-1"),
    )
    assert d_nsf.action is DecisionAction.ROUTE  # 0.9 < 0.99 ⇒ defer
    assert d_nsf.reason is RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY
    assert d_rev.action is DecisionAction.ACCEPT  # 0.9 > 0.80 ⇒ predict
    assert d_rev.reason is AcceptReason.CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY


# ---------------------------------------------------------------------------------------
# Invariant 6 — deferral cost is instance-dependent: l_exp(x,y,m) = 1[m≠y] + c(x).
# Mozannar & Sontag §3, verbatim: "such additive costs can be easily integrated into our
# analysis."
# ---------------------------------------------------------------------------------------
def test_invariant_6_instance_dependent_deferral_cost():
    from abstention.deferral.reviewer_model import DeferralCost

    cost = DeferralCost(per_field_minutes={FieldType.NSF_COUNT: 0.5, FieldType.GROSS_REVENUE: 4.0})
    # 1[m≠y] term
    assert cost.expert_loss(FieldType.NSF_COUNT, expert_correct=True) == pytest.approx(
        cost.c(FieldType.NSF_COUNT)
    )
    assert cost.expert_loss(FieldType.NSF_COUNT, expert_correct=False) == pytest.approx(
        1.0 + cost.c(FieldType.NSF_COUNT)
    )
    # c(x) varies by instance
    assert cost.c(FieldType.GROSS_REVENUE) > cost.c(FieldType.NSF_COUNT)


# ---------------------------------------------------------------------------------------
# Invariant 7 — coverage control uses the CheXpert percentile protocol EXACTLY.
# Mozannar & Sontag §6.4, verbatim: sort by q(x) := g_⊥(x) − max(g_0(x), g_1(x)); to
# achieve coverage c, τ = q(x_c) (c'th percentile); defer iff q(x) ≥ τ; "the definition
# of τ ensures that we obtain exactly c% coverage."
# ---------------------------------------------------------------------------------------
def test_invariant_7_chexpert_percentile_protocol_exact_coverage():
    from abstention.deferral.budget import chexpert_coverage_control

    q = [i / 100 for i in range(100)]  # deferral scores for 100 items
    result = chexpert_coverage_control(q_scores=q, coverage_pct=80)

    assert result.tau == pytest.approx(sorted(q)[80], abs=1e-9)  # 80th percentile
    deferred = [i for i, qi in enumerate(q) if qi >= result.tau]
    assert result.deferred_indices == deferred
    assert len(deferred) == 20  # exactly (100 − c)% deferred ⇒ exactly c% coverage


# ---------------------------------------------------------------------------------------
# Invariant 8 — union-bound discipline: SGR's binary search over k = ⌈log₂ m⌉ thresholds
# spends δ/k per bound call. Geifman & El-Yaniv Algorithm 1 line 9 + Theorem 3.2.
# ---------------------------------------------------------------------------------------
def test_invariant_8_sgr_spends_delta_over_k():
    import math

    from abstention.conformal.sgr import sgr

    m = 200
    rng_conf = [i / m for i in range(m)]
    losses = [1 if i % 7 == 0 else 0 for i in range(m)]
    result = sgr(confidences=rng_conf, losses=losses, delta=0.001, r_star=0.05)

    k = math.ceil(math.log2(m))
    assert result.k == k
    assert len(result.audit) == k  # one bound call per binary-search iteration
    for call in result.audit:
        assert call.delta == pytest.approx(0.001 / k)  # δ/k, never δ


# ---------------------------------------------------------------------------------------
# Invariant 9 — format/normalization mismatches are NOT errors; the oracle normalizes
# before comparing. Kamath §5.6: 62% of the worst overconfidence errors were valid
# alternate answers or span mismatches.
# ---------------------------------------------------------------------------------------
def test_invariant_9_correctness_oracle_normalizes_before_comparing():
    from abstention.oracle.correctness import CorrectnessOracle

    oracle = CorrectnessOracle()
    assert oracle.values_equivalent("1,234.00", Decimal("1234"))
    assert oracle.values_equivalent("(1,234)", Decimal("-1234"))  # parenthesized negative
    assert oracle.values_equivalent("1,234", Decimal("1234000"), thousands_scaled=True)
    assert not oracle.values_equivalent("1,234.00", Decimal("1235"))


# ---------------------------------------------------------------------------------------
# Invariant 10 — fairness is measured END-TO-END on the composed system, never
# component-wise. Mozannar & Sontag §6.5: classifier 0.226 + fair expert 0.03 → composed
# 0.449; direction not predictable from components.
# ---------------------------------------------------------------------------------------
def test_invariant_10_fairness_measured_end_to_end():
    from abstention.telemetry.fairness import end_to_end_disparate_impact

    # Composed decisions (post model+reviewer), keyed by segment axis value.
    # (decided_positive, truth_positive) per case, after the FULL pipeline.
    outcomes = {
        "42": [(True, False), (True, True), (False, False), (True, False)],
        "72": [(False, False), (True, True), (True, False), (False, True)],
    }
    report = end_to_end_disparate_impact(outcomes)

    # FPR = FP/negatives on the COMPOSED output: "42" = 2/3, "72" = 1/2.
    assert report.fpr_by_group["42"] == pytest.approx(2 / 3)
    assert report.fpr_by_group["72"] == pytest.approx(1 / 2)
    assert report.max_gap == pytest.approx(2 / 3 - 1 / 2)
    assert report.worst_group == "42"


# ---------------------------------------------------------------------------------------
# Invariant 11 — Path 1 / Path 2 / Path 3 never share a mechanism. Kamath §5.7.
# Domain-level: GREEN from step 3.
# ---------------------------------------------------------------------------------------
def test_invariant_11_paths_never_share_a_mechanism():
    from abstention.domain.paths import AbsenceReport, discriminate

    class ExactComparator:
        def equivalent(self, a, b):
            return a.value == b.value

    # Path 1 is produced by the detector's refusal — no confidence exists anywhere.
    absent = discriminate(
        FieldType.DEPRECIATION,
        extractions=(),
        absence=AbsenceReport(
            field_type=FieldType.DEPRECIATION,
            reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT,
            detector_id="absence-v1",
        ),
        comparator=ExactComparator(),
    )
    assert isinstance(absent, Path1Absent)
    assert not hasattr(absent, "calibrated_confidence")  # no confidence surface at all

    # Path 3 fires at confidence 0.99 on both sources — confidence is irrelevant.
    a = _ext(value="100000", conf=0.99, doc="bank-stmt")
    b = _ext(value="180000", conf=0.99, doc="tax-1120s")
    contradicted = discriminate(
        FieldType.GROSS_REVENUE, extractions=(a, b), absence=None, comparator=ExactComparator()
    )
    assert isinstance(contradicted, Path3Contradicted)

    # And neither Path 1 nor Path 3 can be resolved by any confidence threshold: the only
    # resolution surface is a ROUTE decision; ACCEPT raises at construction.
    with pytest.raises(PathViolationError):
        FieldDecision(
            outcome=contradicted,
            action=DecisionAction.ACCEPT,
            reason=AcceptReason.CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY,
        )
    with pytest.raises(PathViolationError):
        FieldDecision(
            outcome=absent,
            action=DecisionAction.ACCEPT,
            reason=AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD,
        )


# ---------------------------------------------------------------------------------------
# Invariant 12 — every decision carries a closed-enum reason; free text is forbidden at
# the type level. Domain-level: GREEN from step 3.
# ---------------------------------------------------------------------------------------
def test_invariant_12_closed_enum_reasons_no_free_text():
    assert TAXONOMY_VERSION == "1.1.0"

    # The taxonomy is exactly the specified closed set — additions/removals are a version event.
    # 1.1.0 removed the two never-emitted budget/coverage reasons (audit F5).
    assert {r.name for r in RouteReason} == {
        "FIELD_ABSENT_FROM_DOCUMENT",
        "DOCUMENT_ARCHETYPE_UNSUPPORTED",
        "CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY",
        "CONFORMITY_SCORE_ABOVE_THRESHOLD",
        "NO_CONFIDENCE_AVAILABLE",
        "CROSS_DOCUMENT_VALUE_CONFLICT",
        "ACCRUAL_CASH_DIVERGENCE",
        "EXTRACTION_ERROR",
    }
    assert {r.name for r in AcceptReason} == {
        "CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY",
        "CONFORMITY_SCORE_WITHIN_THRESHOLD",
    }
    assert set(ROUTE_REASON_GROUP) == set(RouteReason)  # exhaustive grouping

    outcome = Path2Scored(
        field_type=FieldType.GROSS_REVENUE,
        extractions=(_ext(),),
        primary=_ext(),
        calibrated_confidence=0.4,
    )
    # Free text — even text that spells a valid member — is rejected by type.
    with pytest.raises(TypeError):
        FieldDecision(outcome=outcome, action=DecisionAction.ROUTE, reason="looked sketchy")
    with pytest.raises(TypeError):
        FieldDecision(
            outcome=outcome, action=DecisionAction.ROUTE, reason="CONFORMITY_SCORE_ABOVE_THRESHOLD"
        )
    # The enum member itself is the only accepted currency.
    ok = FieldDecision(
        outcome=outcome,
        action=DecisionAction.ROUTE,
        reason=RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD,
    )
    assert ok.reason is RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD
