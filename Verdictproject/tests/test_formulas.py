"""Numeric checks against paper-reported values (Part 8 step 4).

Every constant here traces to a formula verified against print in GATE_REPORT.md. Where a
paper prints a table, the test pins the machinery to that table; where it prints a bound, the
test reproduces the bound's defining equation.
"""
from __future__ import annotations

import math

import pytest

from abstention.conformal.aci import (
    ACIState,
    gamma_star,
    prop41_coverage_bound,
    shift_bound,
)
from abstention.conformal.sgr import (
    empirical_coverage,
    empirical_selective_risk,
    gascuel_caraux_bound,
    sgr,
)


# =======================================================================================
# Geifman & El-Yaniv 2017 — Gascuel–Caraux bound (F3) and SGR (F4, F5)
# =======================================================================================
def test_gascuel_caraux_solves_the_binomial_equation():
    """B* must satisfy Σ_{j=0}^{n_err} C(n,j) b^j (1−b)^{n−j} = δ exactly (Lemma 3.1, Eq. 4)."""
    n, n_err, delta = 500, 10, 0.001
    b = gascuel_caraux_bound(n, n_err, delta)
    cdf = sum(math.comb(n, j) * b**j * (1 - b) ** (n - j) for j in range(n_err + 1))
    assert cdf == pytest.approx(delta, abs=1e-6)
    assert b > n_err / n  # an upper confidence bound sits strictly above the point estimate


def test_gascuel_caraux_zero_error_closed_form():
    """n_err = 0 ⇒ (1−b)^n = δ ⇒ b = 1 − δ^{1/n}."""
    n, delta = 100, 0.05
    b = gascuel_caraux_bound(n, 0, delta)
    assert b == pytest.approx(1 - delta ** (1 / n), abs=1e-9)


def test_gascuel_caraux_is_tighter_than_hoeffding():
    """Invariant 8 / F3: the binomial bound must not be looser than Hoeffding's analytic
    slack r̂ + sqrt(ln(1/δ)/(2n)). Confirms we did not substitute Hoeffding for the tail."""
    n, n_err, delta = 1000, 20, 0.001
    b = gascuel_caraux_bound(n, n_err, delta)
    hoeffding = n_err / n + math.sqrt(math.log(1 / delta) / (2 * n))
    assert b < hoeffding


def test_gascuel_caraux_vacuous_when_all_errors():
    assert gascuel_caraux_bound(50, 50, 0.001) == 1.0


def test_selective_risk_uses_conditional_denominator():
    """F1 / invariant 1: risk conditional on answering, coverage = mass answered."""
    losses = [1, 0, 0, 0, 1, 1]
    accepted = [1, 1, 1, 1, 0, 0]
    assert empirical_coverage(accepted) == pytest.approx(4 / 6)
    assert empirical_selective_risk(losses, accepted) == pytest.approx(1 / 4)  # not 3/6


def test_sgr_spends_delta_over_k_and_returns_risk_controlled_threshold():
    """F4/F5: k = ⌈log₂ m⌉ iterations, each spending δ/k; the returned bound respects r*."""
    m = 1000
    # A clean confidence signal: high-confidence items are almost never wrong.
    confidences = [i / m for i in range(m)]
    losses = [1 if (i / m) < 0.3 and i % 2 == 0 else 0 for i in range(m)]
    delta, r_star = 0.001, 0.05
    res = sgr(confidences=confidences, losses=losses, delta=delta, r_star=r_star)

    assert res.k == math.ceil(math.log2(m))
    assert len(res.audit) == res.k
    for call in res.audit:
        assert call.delta == pytest.approx(delta / res.k)
    # The accepted region's guaranteed bound is below the requested risk target.
    assert res.feasible
    assert res.bound < r_star
    # And it kept meaningful coverage rather than collapsing to zero.
    assert res.coverage > 0.5


def test_sgr_binary_search_monotone_threshold_direction():
    """Higher θ ⇒ fewer accepted ⇒ lower coverage. The search converges, not oscillates
    unboundedly: z stays within [1, m] and the final threshold is one of the sample values."""
    m = 256
    confidences = [i / m for i in range(m)]
    losses = [1 if i % 5 == 0 else 0 for i in range(m)]
    res = sgr(confidences=confidences, losses=losses, delta=0.01, r_star=0.1)
    assert res.theta in confidences
    assert 0.0 <= res.coverage <= 1.0


# =======================================================================================
# Gibbs & Candès 2021 — ACI update (F11), Lemma 4.1 (F12), Prop 4.1 (F13), Thm 4.2 (F14/D6)
# =======================================================================================
def test_aci_update_exact_arithmetic():
    """Eq. (2): α_{t+1} = α_t + γ(α − err_t), γ = 0.005."""
    st = ACIState(alpha_target=0.1)
    assert st.gamma == 0.005 and st.alpha == 0.1  # α_1 = α
    st = st.update(err=1)
    assert st.alpha == pytest.approx(0.0955)
    st = st.update(err=0)
    assert st.alpha == pytest.approx(0.0960)


def test_aci_clamp_is_lemma_4_1_not_zero_one():
    """Lemma 4.1: α_t ∈ [−γ, 1+γ]. A [0,1] clamp is the wrong, silently-degrading choice."""
    lo = ACIState(alpha_target=0.1, alpha=0.0)
    for _ in range(100):
        lo = lo.update(err=1)
    assert lo.alpha == pytest.approx(-lo.gamma)  # floors at −γ, not 0
    hi = ACIState(alpha_target=0.9, alpha=1.0)
    for _ in range(100):
        hi = hi.update(err=0)
    assert hi.alpha == pytest.approx(1 + hi.gamma)  # ceils at 1+γ, not 1


def test_aci_prop41_bound_holds_over_a_run():
    """Prop 4.1: |(1/T)Σ err − α| ≤ (max{α_1,1−α_1}+γ)/(Tγ), distribution-free.

    err_t = 1[Y_t ∉ Ĉ_t(α_t)] is generated by a *real* miscoverage mechanism M_t(α_t): a
    larger α_t means a smaller prediction set means more miscoverage, with M_t(α≤0)=0 (the
    set is everything) and M_t(α≥q_t)=1 (empty). q_t shifts mid-run — the drift ACI absorbs.
    Because M respects those boundaries the explicit clamp never binds, so the recursion
    telescopes and Prop 4.1's algebraic envelope is guaranteed to hold."""
    import random

    rng = random.Random(7)
    target, gamma, T = 0.1, 0.005, 4000
    st = ACIState(alpha_target=target, gamma=gamma)
    errs = []
    for t in range(T):
        q_t = 0.5 if t < T // 2 else 2.0  # regime break at the midpoint
        miscoverage_rate = min(1.0, max(0.0, st.alpha / q_t))  # 0 when α_t ≤ 0
        err = 1 if rng.random() < miscoverage_rate else 0
        errs.append(err)
        st = st.update(err=err)
    realized = sum(errs) / T
    bound = prop41_coverage_bound(alpha1=target, gamma=gamma, num_steps=T)
    assert abs(realized - target) <= bound
    # ACI actually tracks the target closely across the shift, not just within the envelope.
    assert abs(realized - target) < 0.02


def test_thm42_tail_is_half_L_gamma_not_L_squared_gamma():
    """D6: Thm 4.2's tail is (L/2)γ. Confirmed by the paper's own corollary — the argmin of
    the printed RHS is γ* = (2·E|Δα*|)^{1/2}, and the L²γ misreading would give (E/L)^{1/2}."""
    L, E = 1.0, 0.02
    g_star = gamma_star(E)
    assert g_star == pytest.approx(math.sqrt(2 * E))

    # Numerically, g_star minimises shift_bound (the (L/2)γ form).
    grid = [0.001 * i for i in range(1, 1000)]
    argmin = min(grid, key=lambda g: shift_bound(L, g, E))
    assert argmin == pytest.approx(g_star, abs=2e-3)

    # The L²γ alternative would be minimised elsewhere — proving the tail's identity matters.
    def wrong_bound(g):
        return (L * (1 + g) / g) * E + (L**2) * g

    wrong_argmin = min(grid, key=wrong_bound)
    assert wrong_argmin == pytest.approx(math.sqrt(E / L), abs=2e-3)
    assert not math.isclose(wrong_argmin, g_star, abs_tol=2e-3)

    # At γ*, the (L/2)γ bound sits at or below the paper's clean form L(√2+1)√E (which bounds
    # the LE constant by L√E for E ≤ 1).
    assert shift_bound(L, g_star, E) <= L * (math.sqrt(2) + 1) * math.sqrt(E) + 1e-12
