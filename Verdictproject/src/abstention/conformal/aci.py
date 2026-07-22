"""Adaptive Conformal Inference — the online α_t update and its distribution-free bounds.

Gibbs & Candès 2021 (verified against print, GATE_REPORT.md F11–F14):

  F11  Eq. (2):     α_{t+1} := α_t + γ(α − err_t)
  F12  Lemma 4.1:   with probability one, ∀t, α_t ∈ [−γ, 1+γ]        ← NOT [0, 1]
  F13  Prop 4.1:    |(1/T)Σ err_t − α| ≤ (max{α_1, 1−α_1} + γ)/(Tγ)  (distribution-free)
  F14  Thm 4.2:     E[(M(α_t|A_t) − α)²] ≤ (L(1+γ)/γ)·E|Δα*| + (L/2)γ

No regret-bound machinery: the authors made the OGD connection "only in passing" and
declined to lean on it (invariant 3).

DISCREPANCIES.md D6: the Thm 4.2 tail term is (L/2)γ, not the L²γ the synthesis's garbled
extraction suggested. Confirmed because minimizing the printed RHS reproduces the paper's own
corollary γ* = (2·E|Δα*|)^{1/2}; L²γ would instead give γ* = (E/L)^{1/2}, contradicting print.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

DEFAULT_GAMMA = 0.005  # Gibbs & Candès §2.2 experiments; configs/baseline.yaml default


@dataclass(frozen=True, slots=True)
class ACIState:
    """One coordinate of the ACI recursion. Immutable: update() returns a new state.

    alpha_target is the miscoverage target α (e.g. 0.1 for 90% coverage). alpha is the
    online estimate α_t; it initialises to α_1 = α (Gibbs §2, "in our experiments we will
    choose α_1 = α"). alpha is clamped to Lemma 4.1's [−γ, 1+γ], never to [0, 1] — clipping
    to [0,1] silently breaks the recursion's dynamics (a top silent-failure risk, Part 1).
    """

    alpha_target: float
    alpha: float | None = None
    gamma: float = DEFAULT_GAMMA

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha_target < 1.0):
            raise ValueError("alpha_target must be in (0, 1)")
        if self.gamma <= 0.0:
            raise ValueError("gamma must be > 0")
        if self.alpha is None:
            object.__setattr__(self, "alpha", self.alpha_target)  # α_1 = α
        object.__setattr__(self, "alpha", self._clamp(self.alpha))

    def _clamp(self, a: float) -> float:
        return min(max(a, -self.gamma), 1.0 + self.gamma)  # Lemma 4.1

    def update(self, err: int) -> "ACIState":
        """Apply Eq. (2). err ∈ {0,1} is 1[Y_t ∉ Ĉ_t(α_t)]."""
        if err not in (0, 1):
            raise ValueError("err must be 0 or 1 (an indicator of miscoverage)")
        nxt = self.alpha + self.gamma * (self.alpha_target - err)
        return replace(self, alpha=self._clamp(nxt))


def prop41_coverage_bound(alpha1: float, gamma: float, num_steps: int) -> float:
    """Proposition 4.1 RHS: (max{α_1, 1−α_1} + γ)/(Tγ) — the distribution-free envelope on
    |empirical miscoverage − α| after T steps. Puts no constraint on the data distribution."""
    if num_steps < 1:
        raise ValueError("num_steps must be >= 1")
    return (max(alpha1, 1.0 - alpha1) + gamma) / (num_steps * gamma)


def shift_bound(lipschitz: float, gamma: float, expected_shift: float) -> float:
    """Theorem 4.2 RHS (F14, with the D6-corrected (L/2)γ tail):

        (L(1+γ)/γ)·E|Δα*| + (L/2)γ

    expected_shift is E|α*_{A_{t+1}} − α*_{A_t}|, the paper's quantitative shift measure
    (telemetry/shift.py estimates it empirically and feeds it here)."""
    if lipschitz <= 0 or gamma <= 0 or expected_shift < 0:
        raise ValueError("lipschitz>0, gamma>0, expected_shift>=0 required")
    return (lipschitz * (1.0 + gamma) / gamma) * expected_shift + (lipschitz / 2.0) * gamma


def gamma_star(expected_shift: float) -> float:
    """The step size that minimises Theorem 4.2's bound: γ* = (2·E|Δα*|)^{1/2}
    (Gibbs & Candès, remark after Thm 4.2). Formalises "γ larger in domains with greater
    shift, but not so large that α_t becomes volatile.\""""
    if expected_shift < 0:
        raise ValueError("expected_shift must be >= 0")
    return math.sqrt(2.0 * expected_shift)
