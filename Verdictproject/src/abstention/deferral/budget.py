"""Coverage control against a finite reviewer budget — the CheXpert percentile protocol (F10).

Mozannar & Sontag §6.4 (verified, verbatim): sort by q(x) := g_⊥(x) − max(g_0(x), g_1(x));
to achieve coverage c, set τ = q(x_c), the c-th percentile of q; defer iff q(x) ≥ τ. "The
definition of τ ensures that we obtain exactly c% coverage." Invariant 7 forbids inventing an
alternative thresholding scheme — this is that protocol, unchanged.

Here q(x) is the deferral score (higher ⇒ more deferral-worthy); for the field layer it is the
conformity score / (1 − calibrated confidence). ReviewerBudget tracks the finite human budget
and its burn (a first-class frontend surface, Part 7 decision 4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class CoverageControlResult:
    tau: float
    deferred_indices: list[int]
    accepted_indices: list[int]
    realized_coverage: float


def chexpert_coverage_control(
    q_scores: Sequence[float], coverage_pct: float
) -> CoverageControlResult:
    """τ = the coverage_pct-th percentile of q; defer iff q ≥ τ. Exactly coverage_pct% is
    accepted by construction (up to ties)."""
    n = len(q_scores)
    if n == 0:
        raise ValueError("q_scores must be non-empty")
    if not (0.0 <= coverage_pct <= 100.0):
        raise ValueError("coverage_pct must be in [0, 100]")
    ordered = sorted(q_scores)
    idx = int(round(coverage_pct / 100.0 * n))
    tau = ordered[idx] if idx < n else ordered[-1] + 1e-9  # accept all when 100% coverage
    deferred = [i for i, q in enumerate(q_scores) if q >= tau]
    accepted = [i for i, q in enumerate(q_scores) if q < tau]
    return CoverageControlResult(
        tau=tau,
        deferred_indices=deferred,
        accepted_indices=accepted,
        realized_coverage=len(accepted) / n,
    )


@dataclass
class ReviewerBudget:
    """A finite per-batch human review budget with burn tracking. Degraded items consume
    budget too (Part 6: "INCLUDED in budget burn") — spend() is called for every routed item
    regardless of why it routed.

    TELEMETRY ONLY (audit F5): this tracks and surfaces burn; it does NOT gate routing. A
    calibrated route/accept decision is a safety decision and must not be flipped by reviewer
    capacity (a contradiction or an uncertain field routes regardless of remaining budget).
    The removed `can_route()` and the two never-emitted budget/coverage RouteReasons implied a
    control the system deliberately does not exercise."""

    total: int
    spent: int = 0

    def __post_init__(self) -> None:
        if self.total < 0:
            raise ValueError("budget total must be >= 0")

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.spent)

    @property
    def burn_fraction(self) -> float:
        return self.spent / self.total if self.total else 1.0

    def spend(self, n: int = 1) -> None:
        self.spent += n
