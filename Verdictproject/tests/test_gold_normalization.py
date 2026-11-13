"""Gold derivation: scale, sign, period and absent-field handling on hand-built cases."""
from decimal import Decimal

from _real_helpers import facts_10q
from abstention.data import gold_labels as gl
from abstention.data.sec_schema import SecField


def test_10q_uses_three_month_income_and_ytd_cashflow():
    g = gl.derive_gold(facts_10q(), period_end="2026-09-30", form="10-Q")
    assert g[SecField.REVENUE].value == Decimal(98765000)            # 3-month, not the 9-month 270M
    assert g[SecField.DEPRECIATION_AMORTIZATION].value == Decimal(6000000)  # YTD cash-flow column
    assert g[SecField.NET_INCOME].value == Decimal(-5678000)         # sign preserved


def test_10k_uses_full_year_and_balance_uses_period_end():
    facts = [{"tag": "Revenues", "value": 1000, "start": "2025-10-01", "end": "2026-09-30", "dimensional": False},
             {"tag": "Revenues", "value": 250, "start": "2026-07-01", "end": "2026-09-30", "dimensional": False},
             {"tag": "Assets", "value": 5, "end": "2026-09-30", "dimensional": False},
             {"tag": "Assets", "value": 4, "end": "2025-09-30", "dimensional": False}]
    g = gl.derive_gold(facts, period_end="2026-09-30", form="10-K")
    assert g[SecField.REVENUE].value == Decimal(1000)
    assert g[SecField.TOTAL_ASSETS].value == Decimal(5)               # not the prior-year column


def test_missing_tag_is_absent_not_zero():
    g = gl.derive_gold(facts_10q(), period_end="2026-09-30", form="10-Q")
    assert g[SecField.INTEREST_EXPENSE].status == gl.GoldStatus.ABSENT
    assert g[SecField.TOTAL_LIABILITIES].status == gl.GoldStatus.ABSENT
    assert g[SecField.INTEREST_EXPENSE].value is None


def test_conflicting_duplicates_and_excluded_variant_are_ambiguous():
    dup = [{"tag": "Assets", "value": 1, "end": "2026-09-30", "dimensional": False},
           {"tag": "Assets", "value": 2, "end": "2026-09-30", "dimensional": False}]
    assert gl.derive_gold(dup, period_end="2026-09-30", form="10-Q")[SecField.TOTAL_ASSETS].status == gl.GoldStatus.AMBIGUOUS
    restricted = [{"tag": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "value": 9,
                   "end": "2026-09-30", "dimensional": False}]
    assert gl.derive_gold(restricted, period_end="2026-09-30", form="10-Q")[SecField.CASH].status == gl.GoldStatus.AMBIGUOUS


def test_dimensional_facts_are_ignored():
    f = [{"tag": "Assets", "value": 7, "end": "2026-09-30", "dimensional": True}]
    assert gl.derive_gold(f, period_end="2026-09-30", form="10-Q")[SecField.TOTAL_ASSETS].status == gl.GoldStatus.ABSENT


def _gold(field, value):
    return gl.GoldValue(field, gl.GoldStatus.FOUND, Decimal(value), "T", "2026-09-30")


def test_scale_is_normalised_and_wrong_scale_is_an_error():
    g = _gold(SecField.TOTAL_ASSETS, 1234567000)
    assert gl.is_error(g, extractor_status="found", extracted_value=Decimal("1234567"), scale="thousands") == 0
    assert gl.is_error(g, extractor_status="found", extracted_value=Decimal("1234567"), scale="units") == 1   # scale trap
    assert gl.is_error(g, extractor_status="found", extracted_value=Decimal("1234.567"), scale="millions") == 0


def test_sign_rules_signed_vs_magnitude():
    ni = _gold(SecField.NET_INCOME, -5678000)
    assert gl.is_error(ni, extractor_status="found", extracted_value=Decimal(-5678), scale="thousands") == 0
    assert gl.is_error(ni, extractor_status="found", extracted_value=Decimal(5678), scale="thousands") == 1    # sign matters
    ie = _gold(SecField.INTEREST_EXPENSE, 1111000)
    assert gl.is_error(ie, extractor_status="found", extracted_value=Decimal(-1111), scale="thousands") == 0   # magnitude


def test_absent_logic():
    absent = gl.GoldValue(SecField.INTEREST_EXPENSE, gl.GoldStatus.ABSENT, None, None, "x")
    assert gl.is_error(absent, extractor_status="absent", extracted_value=None, scale="units") == 0
    assert gl.is_error(absent, extractor_status="found", extracted_value=Decimal(5), scale="units") == 1       # hallucination
    found = _gold(SecField.CASH, 100)
    assert gl.is_error(found, extractor_status="absent", extracted_value=None, scale="units") == 1             # miss
    amb = gl.GoldValue(SecField.CASH, gl.GoldStatus.AMBIGUOUS, None, None, "x")
    assert gl.is_error(amb, extractor_status="found", extracted_value=Decimal(1), scale="units") is None       # not evaluable
