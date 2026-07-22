"""Accrual-divergence indices — Beneish METHODOLOGY, NEW coefficients (Part 2, non-goals).

Beneish 1999 states the M-Score "cannot be reliably used to study privately held companies"
(limitation 1, verified against the corrected Jan-2004 printing). So this module imports his
METHODOLOGY, never his betas:

  1. indices built as year-over-year ratio-of-ratios (catch internal inconsistency, not level);
  2. winsorize at 1/99; neutral-fill undefined denominators at 1 (his own AQI/DEPI/SGAI rule);
  3. cutoffs selected by explicit ECM with a defended cost ratio (ecm.py-style), benchmarked
     against the all-clean naive strategy with the crossover cost ratio reported;
  4. the re-estimation sample for SMBs is UNAVAILABLE — that unavailability IS the finding,
     written down here rather than papered over.

DISCREPANCIES.md D1: Beneish's TATA includes the "− Depreciation & Amortization" term the
synthesis dropped. The definitions below carry it, matching Table 2 of the paper.

No adversarial/coordinated-fraud claim is made (Part 5 non-goal). TATA's cross-document accrual
vs. cash divergence is a thin lead toward Path 3, treated as a limitation, not a feature.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

NEUTRAL = Decimal(1)  # neutral-fill value for undefined denominators (Beneish's rule)


def _ratio(numer: Decimal, denom: Decimal) -> Decimal:
    """Ratio with Beneish neutral-fill: an undefined (zero) denominator yields 1, not an
    error and not a drop (Table-2 notes: AQI/DEPI/SGAI set to 1 when undefined)."""
    if denom == 0:
        return NEUTRAL
    return numer / denom


@dataclass(frozen=True, slots=True)
class YearFinancials:
    receivables: Decimal
    sales: Decimal
    cogs: Decimal
    current_assets: Decimal
    ppe: Decimal
    total_assets: Decimal
    depreciation: Decimal
    sga: Decimal
    ltd: Decimal
    current_liabilities: Decimal
    cash: Decimal
    current_maturities_ltd: Decimal
    income_tax_payable: Decimal
    depreciation_amortization: Decimal


def dsri(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Days' Sales in Receivables Index = (Recv_t/Sales_t) / (Recv_{t-1}/Sales_{t-1})."""
    return _ratio(_ratio(t.receivables, t.sales), _ratio(p.receivables, p.sales))


def gmi(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Gross Margin Index = GM_{t-1} / GM_t (deterioration ⇒ > 1)."""
    gm_t = _ratio(t.sales - t.cogs, t.sales)
    gm_p = _ratio(p.sales - p.cogs, p.sales)
    return _ratio(gm_p, gm_t)


def aqi(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Asset Quality Index (two-term numerator; DISCREPANCIES.md D3 confirms no Securities
    term in the 1999 printing)."""
    q_t = Decimal(1) - _ratio(t.current_assets + t.ppe, t.total_assets)
    q_p = Decimal(1) - _ratio(p.current_assets + p.ppe, p.total_assets)
    return _ratio(q_t, q_p)


def sgi(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Sales Growth Index = Sales_t / Sales_{t-1}."""
    return _ratio(t.sales, p.sales)


def depi(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Depreciation Index = rate_{t-1} / rate_t, rate = Dep/(Dep+PP&E)."""
    rate_t = _ratio(t.depreciation, t.depreciation + t.ppe)
    rate_p = _ratio(p.depreciation, p.depreciation + p.ppe)
    return _ratio(rate_p, rate_t)


def sgai(t: YearFinancials, p: YearFinancials) -> Decimal:
    """SG&A Index = (SGA_t/Sales_t) / (SGA_{t-1}/Sales_{t-1})."""
    return _ratio(_ratio(t.sga, t.sales), _ratio(p.sga, p.sales))


def lvgi(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Leverage Index = lev_t / lev_{t-1}, lev = (LTD+CL)/TA."""
    lev_t = _ratio(t.ltd + t.current_liabilities, t.total_assets)
    lev_p = _ratio(p.ltd + p.current_liabilities, p.total_assets)
    return _ratio(lev_t, lev_p)


def tata(t: YearFinancials, p: YearFinancials) -> Decimal:
    """Total Accruals to Total Assets (D1: INCLUDES − Depreciation & Amortization):

        [ ΔCA − ΔCash − (ΔCL − ΔCurrMatLTD − ΔTaxPayable) − D&A_t ] / TotalAssets_t
    """
    d_ca = t.current_assets - p.current_assets
    d_cash = t.cash - p.cash
    d_cl = t.current_liabilities - p.current_liabilities
    d_cmltd = t.current_maturities_ltd - p.current_maturities_ltd
    d_taxp = t.income_tax_payable - p.income_tax_payable
    numer = d_ca - d_cash - (d_cl - d_cmltd - d_taxp) - t.depreciation_amortization
    return _ratio(numer, t.total_assets)


def winsorize(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    """Winsorize at the 1st/99th percentile bounds (Beneish preprocessing). lo/hi are the
    empirical percentile cut points from the reference sample."""
    return min(max(value, lo), hi)
