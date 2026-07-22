"""Exhaustive three-path discrimination (Part 2). Every field outcome maps to exactly one
path; no code path lets Path 1 or Path 3 be resolved by a confidence threshold; Path 3
fires at confidence 0.99. Domain-level — GREEN from step 3."""
from __future__ import annotations

from decimal import Decimal

import pytest

from abstention.domain.models import (
    DecisionAction,
    DegradedItem,
    ExtractedField,
    FieldDecision,
    Path1Absent,
    Path2Scored,
    Path3Contradicted,
    PathViolationError,
    Provenance,
)
from abstention.domain.paths import (
    AbsenceReport,
    UndiscriminableFieldError,
    discriminate,
    path_of,
)
from abstention.domain.taxonomy import AcceptReason, RouteReason
from abstention.domain.types import AnomalyPath, FieldType


class ExactComparator:
    def equivalent(self, a, b):
        return a.value == b.value


class NormalizingComparator:
    """Stand-in for oracle/correctness.py: values within 0.5% are the same number in a
    different costume (invariant 9)."""

    def equivalent(self, a, b):
        if a.value == b.value:
            return True
        denom = max(abs(a.value), abs(b.value))
        return denom != 0 and abs(a.value - b.value) / denom <= Decimal("0.005")


def _prov(doc="doc-1", page=1, span="1,234.00"):
    return Provenance(doc_id=doc, page=page, bbox=(0.1, 0.2, 0.3, 0.25), raw_span=span)


def _ext(ft=FieldType.GROSS_REVENUE, value="1234", conf=0.9, doc="doc-1", span="1,234.00"):
    return ExtractedField(
        field_type=ft, value=Decimal(value), provenance=_prov(doc=doc, span=span), raw_confidence=conf
    )


ABSENCE = AbsenceReport(
    field_type=FieldType.DEPRECIATION,
    reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT,
    detector_id="absence-v1",
)


# --------------------------------------------------------------------------------------
# Exhaustiveness: every discriminable input lands in exactly one of the three paths.
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "extractions, absence, expected_path",
    [
        ((), ABSENCE, AnomalyPath.PATH_1_ABSENT),
        ((_ext(ft=FieldType.DEPRECIATION, value="500"),), None, AnomalyPath.PATH_2_UNCERTAIN),
        (
            (
                _ext(ft=FieldType.DEPRECIATION, value="500", doc="pnl"),
                _ext(ft=FieldType.DEPRECIATION, value="500", doc="tax"),
            ),
            None,
            AnomalyPath.PATH_2_UNCERTAIN,
        ),
        (
            (
                _ext(ft=FieldType.DEPRECIATION, value="500", doc="pnl"),
                _ext(ft=FieldType.DEPRECIATION, value="900", doc="tax"),
            ),
            None,
            AnomalyPath.PATH_3_CONTRADICTED,
        ),
    ],
)
def test_every_outcome_maps_to_exactly_one_path(extractions, absence, expected_path):
    outcome = discriminate(
        FieldType.DEPRECIATION, extractions=extractions, absence=absence, comparator=ExactComparator()
    )
    assert path_of(outcome) is expected_path
    # exactly one: the outcome is an instance of precisely one path type
    kinds = [
        isinstance(outcome, Path1Absent),
        isinstance(outcome, Path2Scored),
        isinstance(outcome, Path3Contradicted),
    ]
    assert sum(kinds) == 1


def test_no_evidence_at_all_is_degraded_not_a_path():
    """Extractor produced nothing and the absence detector said nothing: that is an
    operational failure (Part 6) — excluded from calibration, included in budget burn —
    not a fourth path and not a silent Path 1."""
    with pytest.raises(UndiscriminableFieldError):
        discriminate(FieldType.NSF_COUNT, extractions=(), absence=None, comparator=ExactComparator())

    item = DegradedItem(
        field_type=FieldType.NSF_COUNT, reason=RouteReason.EXTRACTION_ERROR, detail="extractor raised"
    )
    assert item.reason is RouteReason.EXTRACTION_ERROR
    # Degraded items may not masquerade as path outcomes:
    with pytest.raises(PathViolationError):
        DegradedItem(
            field_type=FieldType.NSF_COUNT,
            reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT,  # PATH_1 reason on a degradation
            detail="nope",
        )


# --------------------------------------------------------------------------------------
# Path 1 — extraction refusal. No confidence anywhere; separate detector owns it.
# --------------------------------------------------------------------------------------
def test_path1_comes_only_from_the_absence_detector():
    outcome = discriminate(
        FieldType.DEPRECIATION, extractions=(), absence=ABSENCE, comparator=ExactComparator()
    )
    assert isinstance(outcome, Path1Absent)
    assert outcome.detector_id == "absence-v1"
    assert outcome.reason is RouteReason.FIELD_ABSENT_FROM_DOCUMENT
    # An extracted value means the field is present — the absence report is then moot.
    present = discriminate(
        FieldType.DEPRECIATION,
        extractions=(_ext(ft=FieldType.DEPRECIATION, value="500"),),
        absence=ABSENCE,
        comparator=ExactComparator(),
    )
    assert isinstance(present, Path2Scored)


def test_path1_reason_must_be_a_path1_reason():
    with pytest.raises(ValueError):
        AbsenceReport(
            field_type=FieldType.DEPRECIATION,
            reason=RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD,  # PATH_2 reason
            detector_id="absence-v1",
        )
    with pytest.raises(PathViolationError):
        Path1Absent(
            field_type=FieldType.DEPRECIATION,
            reason=RouteReason.NO_CONFIDENCE_AVAILABLE,  # PATH_2 reason
            detector_id="absence-v1",
        )


# --------------------------------------------------------------------------------------
# Path 3 — reconciliation, not confidence. Fires at 0.99; always routes; never budgeted
# away; points at every conflicting source.
# --------------------------------------------------------------------------------------
def test_path3_fires_at_confidence_099():
    a = _ext(value="100000", conf=0.99, doc="bank-stmt", span="$100,000.00")
    b = _ext(value="180000", conf=0.99, doc="tax-1120s", span="180,000")
    outcome = discriminate(
        FieldType.GROSS_REVENUE, extractions=(a, b), absence=None, comparator=NormalizingComparator()
    )
    assert isinstance(outcome, Path3Contradicted)
    # Both conflicting sources remain addressable for the reviewer and the examiner.
    assert {e.provenance.doc_id for e in outcome.extractions} == {"bank-stmt", "tax-1120s"}


def test_path3_is_not_triggered_by_normalization_artifacts():
    """1,234.00 vs 1234 is the same number (invariant 9) — Path 3 must not fire."""
    a = _ext(value="1234", doc="pnl", span="1,234.00")
    b = _ext(value="1234.00", doc="balance", span="1234")
    outcome = discriminate(
        FieldType.GROSS_REVENUE, extractions=(a, b), absence=None, comparator=NormalizingComparator()
    )
    assert isinstance(outcome, Path2Scored)


def test_path3_always_routes_and_cannot_be_accepted_or_relabeled():
    a = _ext(value="100000", conf=0.99, doc="bank-stmt")
    b = _ext(value="180000", conf=0.99, doc="tax-1120s")
    outcome = Path3Contradicted(field_type=FieldType.GROSS_REVENUE, extractions=(a, b))

    # ACCEPT is a type-level impossibility, at any confidence.
    with pytest.raises(PathViolationError):
        FieldDecision(
            outcome=outcome,
            action=DecisionAction.ACCEPT,
            reason=AcceptReason.CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY,
        )
    # An operational reason may not relabel the contradiction to an operational route.
    with pytest.raises(PathViolationError):
        FieldDecision(
            outcome=outcome,
            action=DecisionAction.ROUTE,
            reason=RouteReason.EXTRACTION_ERROR,
        )
    # Nor may it borrow a Path-2 confidence reason.
    with pytest.raises(PathViolationError):
        FieldDecision(
            outcome=outcome,
            action=DecisionAction.ROUTE,
            reason=RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY,
        )
    # The only lawful decisions:
    for reason in (RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT, RouteReason.ACCRUAL_CASH_DIVERGENCE):
        d = FieldDecision(outcome=outcome, action=DecisionAction.ROUTE, reason=reason)
        assert d.action is DecisionAction.ROUTE


def test_path3_requires_at_least_two_sources():
    with pytest.raises(PathViolationError):
        Path3Contradicted(field_type=FieldType.GROSS_REVENUE, extractions=(_ext(),))


# --------------------------------------------------------------------------------------
# Path 2 — the confidence machinery's domain. None confidence is preserved, not defaulted.
# --------------------------------------------------------------------------------------
def test_path2_none_confidence_is_preserved_never_defaulted():
    e = _ext(conf=None)
    outcome = discriminate(
        FieldType.GROSS_REVENUE, extractions=(e,), absence=None, comparator=ExactComparator()
    )
    assert isinstance(outcome, Path2Scored)
    assert outcome.primary.raw_confidence is None  # not 0.0, not 0.5 — None
    # Its only lawful routed form is NO_CONFIDENCE_AVAILABLE.
    d = FieldDecision(
        outcome=outcome, action=DecisionAction.ROUTE, reason=RouteReason.NO_CONFIDENCE_AVAILABLE
    )
    assert d.reason is RouteReason.NO_CONFIDENCE_AVAILABLE


def test_path2_primary_prefers_highest_raw_confidence():
    lo = _ext(value="1234", conf=0.4, doc="pnl")
    hi = _ext(value="1234", conf=0.95, doc="bank")
    outcome = discriminate(
        FieldType.GROSS_REVENUE, extractions=(lo, hi), absence=None, comparator=ExactComparator()
    )
    assert isinstance(outcome, Path2Scored)
    assert outcome.primary is hi


# --------------------------------------------------------------------------------------
# Construction contracts shared by all paths.
# --------------------------------------------------------------------------------------
def test_extracted_field_requires_decimal_not_float():
    with pytest.raises(TypeError):
        ExtractedField(
            field_type=FieldType.GROSS_REVENUE,
            value=1234.0,  # float — forbidden for monetary values (Part 6)
            provenance=_prov(),
            raw_confidence=0.9,
        )


def test_extracted_field_requires_provenance():
    with pytest.raises(TypeError):
        ExtractedField(
            field_type=FieldType.GROSS_REVENUE,
            value=Decimal("1234"),
            provenance=None,  # a field without provenance is a hard construction error
            raw_confidence=0.9,
        )


def test_provenance_fields_are_all_required_and_validated():
    with pytest.raises(ValueError):
        Provenance(doc_id="", page=1, bbox=(0, 0, 1, 1), raw_span="x")
    with pytest.raises(ValueError):
        Provenance(doc_id="d", page=0, bbox=(0, 0, 1, 1), raw_span="x")
    with pytest.raises(ValueError):
        Provenance(doc_id="d", page=1, bbox=(0, 0, 1, 1), raw_span="")
