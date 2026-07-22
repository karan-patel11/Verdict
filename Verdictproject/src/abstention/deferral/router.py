"""Bayes-optimal deferral router — owns the accept/route decision and nothing else.

Mozannar & Sontag Prop. 2 (F7, invariant 5): defer iff calibrated model confidence < expected
reviewer accuracy on this instance. The router does NOT own budget (budget.py), does NOT own
the conformal threshold (field_loop via aci/sgr), and has NO OOD branch (invariant 4 — OOD is
a calibrator feature already baked into calibrated_confidence upstream; it never routes here).

The router also disposes of the non-Path-2 outcomes structurally: Path 1 (ABSENT) and Path 3
(CONTRADICTED) always route with their own reasons, never by any confidence comparison
(invariant 11). Path 3 routes even at calibrated confidence 0.99.
"""
from __future__ import annotations

from ..domain.models import (
    CalibratorFeatures,
    DecisionAction,
    FieldDecision,
    FieldOutcome,
    Path1Absent,
    Path2Scored,
    Path3Contradicted,
)
from ..domain.taxonomy import AcceptReason, RouteReason


def route_field(
    outcome: FieldOutcome,
    features: CalibratorFeatures | None,
    reviewer_accuracy: float | None,
    contradiction_reason: RouteReason = RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT,
) -> FieldDecision:
    """Decide accept vs route for one discriminated field.

    `features` is accepted for provenance/audit only and MUST NOT influence routing (invariant
    4): OOD-ness lives inside calibrated_confidence, never as a parallel trigger. `reviewer_
    accuracy` is the instance-conditional P(reviewer correct) for Path 2; unused for Paths 1/3.
    """
    if isinstance(outcome, Path1Absent):
        return FieldDecision(outcome=outcome, action=DecisionAction.ROUTE, reason=outcome.reason)

    if isinstance(outcome, Path3Contradicted):
        if contradiction_reason not in (
            RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT,
            RouteReason.ACCRUAL_CASH_DIVERGENCE,
        ):
            raise ValueError("Path 3 must route with a PATH_3 reason")
        return FieldDecision(
            outcome=outcome, action=DecisionAction.ROUTE, reason=contradiction_reason
        )

    # Path 2 — calibrated abstention (the contribution).
    conf = outcome.calibrated_confidence
    if conf is None:
        # Absent score ⇒ route, never default a confidence (Part 6).
        return FieldDecision(
            outcome=outcome,
            action=DecisionAction.ROUTE,
            reason=RouteReason.NO_CONFIDENCE_AVAILABLE,
        )
    if reviewer_accuracy is None:
        raise ValueError("Path 2 routing requires an instance-conditional reviewer_accuracy")

    if conf >= reviewer_accuracy:  # Bayes: predict iff model at least as good as the expert
        return FieldDecision(
            outcome=outcome,
            action=DecisionAction.ACCEPT,
            reason=AcceptReason.CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY,
        )
    return FieldDecision(
        outcome=outcome,
        action=DecisionAction.ROUTE,
        reason=RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY,
    )
