"""Shift telemetry — the quantitative distribution-shift statistic E|α*_{t+1} − α*_t| (F14).

Gibbs & Candès Theorem 4.2 (verified): the bound on realized-vs-target marginal coverage is
controlled by E|α*_{A_{t+1}} − α*_{A_t}|, "the paper's quantitative measurement of distribution
shift size... directly usable as a monitoring statistic in production." α*_t is in one-to-one
correspondence with the (1−α) quantile of the conformity score S_t, so its movement tracks how
non-stationary the score has become (§5) — which, per invariant 2, is exactly what
normalization is meant to keep small.

We estimate α*_t per window as the observed miscoverage-matching level and report the mean
absolute step, alongside the D6-corrected Theorem 4.2 bound (conformal/aci.shift_bound).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..conformal.aci import gamma_star, shift_bound


@dataclass(frozen=True, slots=True)
class ShiftReport:
    expected_shift: float  # E|α*_{t+1} − α*_t|, the monitoring statistic
    per_step: list[float]
    gamma_star: float  # the step size that would minimise Thm 4.2's bound for this shift
    thm42_bound_at_gamma: float  # shift_bound at the ACTUAL gamma in use


def alpha_star_series(miscoverage_by_window: Sequence[float], target_alpha: float) -> list[float]:
    """A simple, monotone proxy for α*_t per window: the level whose realized miscoverage
    matches the target. With the empirical miscoverage m_w in a window, α*_w moves opposite to
    m_w relative to the target (higher realized miscoverage ⇒ the optimal level was lower).
    This is a monitoring proxy, not a calibrated estimate — it tracks MOVEMENT, which is what
    the Theorem 4.2 statistic needs."""
    return [target_alpha - (m - target_alpha) for m in miscoverage_by_window]


def build_shift_report(
    miscoverage_by_window: Sequence[float],
    target_alpha: float,
    gamma_in_use: float,
    lipschitz: float = 1.0,
) -> ShiftReport:
    stars = alpha_star_series(miscoverage_by_window, target_alpha)
    steps = [abs(stars[i + 1] - stars[i]) for i in range(len(stars) - 1)]
    expected = sum(steps) / len(steps) if steps else 0.0
    return ShiftReport(
        expected_shift=expected,
        per_step=steps,
        gamma_star=gamma_star(expected),
        thm42_bound_at_gamma=shift_bound(lipschitz, gamma_in_use, expected),
    )
