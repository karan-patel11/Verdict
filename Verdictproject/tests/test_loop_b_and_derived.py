"""Loop B (case decision) is instrumented, not guaranteed; derived metrics use Beneish
methodology with the corrected TATA; propagation is an unimplemented seam."""
from __future__ import annotations

from decimal import Decimal

import pytest

from abstention.derived import accrual_indices as ai
from abstention.derived.metrics import ADBInputs, DSCRInputs, UndefinedMetricError, adb_ratio, dscr
from abstention.derived.propagation import FieldUncertainty, propagate_to_metric
from abstention.loops.case_loop import (
    CaseLoopGuaranteeError,
    compute_case_metrics,
    decide_case,
    update_coverage_from_case_outcome,
)
from abstention.domain.types import BusinessAgeBucket, RiskTier, Segment

SEG = Segment(industry_naics2="72", geography_state="CA", business_age=BusinessAgeBucket.LT_2Y)


# -------------------------------------------------------------------------------------
# Loop B does not inherit Loop A's guarantee, and refuses to run the ACI update.
# -------------------------------------------------------------------------------------
def test_case_loop_refuses_to_close_the_loop():
    with pytest.raises(CaseLoopGuaranteeError) as exc:
        update_coverage_from_case_outcome(case_id="c1", defaulted=True)
    assert "rejection inference" in str(exc.value).lower() or "delayed" in str(exc.value).lower()


def test_case_decision_never_claims_a_guarantee():
    m = compute_case_metrics(
        net_income=Decimal("120000"), depreciation=Decimal("30000"),
        total_debt_service=Decimal("100000"), avg_daily_balance=Decimal("90000"),
        monthly_debt_service=Decimal("50000"),
    )
    d = decide_case("c1", SEG, m, n_fields_automated=8, n_fields_routed=1)
    assert d.guaranteed is False  # structurally always False


def test_unresolved_or_undefined_routes_case_to_review():
    # DSCR undefined (zero debt service) ⇒ REVIEW, not a fabricated ratio.
    m = compute_case_metrics(Decimal("100000"), Decimal("0"), Decimal("0"), Decimal("50000"), Decimal("40000"))
    assert m.dscr is None and m.undefined_reasons
    assert decide_case("c2", SEG, m, 5, 0).risk_tier is RiskTier.REVIEW
    # A healthy case with an unresolved routed field still goes to REVIEW.
    healthy = compute_case_metrics(Decimal("200000"), Decimal("40000"), Decimal("100000"), Decimal("120000"), Decimal("50000"))
    assert decide_case("c3", SEG, healthy, 7, 2, any_field_routed_unresolved=True).risk_tier is RiskTier.REVIEW


def test_dscr_and_adb_formulas():
    assert dscr(DSCRInputs(Decimal("120000"), Decimal("30000"), Decimal("100000"))) == Decimal("1.5")
    assert adb_ratio(ADBInputs(Decimal("90000"), Decimal("60000"))) == Decimal("1.5")
    with pytest.raises(UndefinedMetricError):
        dscr(DSCRInputs(Decimal("1"), Decimal("1"), Decimal("0")))


# -------------------------------------------------------------------------------------
# Beneish methodology, new betas — TATA carries the −D&A term (DISCREPANCIES.md D1).
# -------------------------------------------------------------------------------------
def _yf(**kw):
    base = dict(
        receivables=Decimal("100"), sales=Decimal("1000"), cogs=Decimal("600"),
        current_assets=Decimal("500"), ppe=Decimal("300"), total_assets=Decimal("1000"),
        depreciation=Decimal("50"), sga=Decimal("100"), ltd=Decimal("200"),
        current_liabilities=Decimal("150"), cash=Decimal("120"),
        current_maturities_ltd=Decimal("20"), income_tax_payable=Decimal("30"),
        depreciation_amortization=Decimal("50"),
    )
    base.update(kw)
    return ai.YearFinancials(**base)


def test_tata_includes_depreciation_amortization_term():
    t = _yf(current_assets=Decimal("560"), cash=Decimal("130"), current_liabilities=Decimal("170"),
            current_maturities_ltd=Decimal("25"), income_tax_payable=Decimal("35"),
            depreciation_amortization=Decimal("50"), total_assets=Decimal("1000"))
    p = _yf()
    # numerator = dCA - dCash - (dCL - dCMLTD - dTaxP) - D&A
    #           = 60 - 10 - (20 - 5 - 5) - 50 = 60 - 10 - 10 - 50 = -10 ; /1000 = -0.01
    assert ai.tata(t, p) == pytest.approx(Decimal("-0.01"))
    # Dropping the D&A term (the synthesis's error) would give +0.04 — a sign flip on the
    # largest-coefficient variable. The corrected formula is materially different.
    assert ai.tata(t, p) != pytest.approx(Decimal("0.04"))


def test_beneish_neutral_fill_on_zero_denominator():
    # Prior-year sales zero ⇒ ratio neutral-filled to 1, not an error or a drop.
    t = _yf(sales=Decimal("1000"))
    p = _yf(sales=Decimal("0"), receivables=Decimal("0"))
    assert ai.sgi(t, p) == Decimal("1")  # Sales_t / 0 -> neutral 1


# -------------------------------------------------------------------------------------
# Propagation is an unimplemented, honestly-flagged seam.
# -------------------------------------------------------------------------------------
def test_propagation_is_not_implemented():
    with pytest.raises(NotImplementedError) as exc:
        propagate_to_metric([FieldUncertainty("NET_INCOME", 0.9)], "DSCR", Decimal("1.5"))
    assert "propagation" in str(exc.value).lower()
