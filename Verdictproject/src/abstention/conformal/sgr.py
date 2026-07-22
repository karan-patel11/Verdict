"""Selection with Guaranteed Risk (SGR) + the Gascuel–Caraux binomial bound + δ/k.

Geifman & El-Yaniv 2017 (verified against print, GATE_REPORT.md F1, F3–F5):

  F1  Eq. (1):        R(f,g) = E[ℓ(f(x),y)g(x)] / φ(f,g),  φ(f,g) = E[g(x)]
                      empirical: r̂ = (1/m Σ ℓ·g) / φ̂,  φ̂ = (1/m)Σ g   (invariant 1:
                      routed items are NOT model errors — conditional denominator)
  F3  Lemma 3.1:      B*(r̂, δ, S_m) solves  Σ_{j=0}^{m·r̂} C(m,j) b^j (1−b)^{m−j} = δ
                      — the tightest bound; Hoeffding merely approximates it (invariant 8's
                      "NOT Hoeffding")
  F4  Algorithm 1:    binary search over k = ⌈log₂ m⌉ thresholds; line 9 spends δ/⌈log₂ m⌉
  F5  Theorem 3.2:    Pr{∃i: R(f|P_{g_i}) > B*(r̂_i, δ/k, g_i(S_m))} < δ  (union bound)

SGR assumes 0/1 loss and i.i.d. sampling from a fixed P; the extraction fields are numeric
and the stream is non-exchangeable, so SGR does not transfer wholesale (the authors name
regression extension as open). What transfers and is used here: the conditional-denominator
selective risk, the Gascuel–Caraux primitive, and the δ/k union-bound discipline. SGR gives a
static per-batch risk-controlled threshold; ACI (aci.py) carries the online guarantee.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def empirical_coverage(accepted: Sequence[int | bool]) -> float:
    """φ̂(f,g|S_m) = (1/m) Σ g(x_i)."""
    m = len(accepted)
    if m == 0:
        raise ValueError("empirical_coverage requires a non-empty sample")
    return sum(1 for a in accepted if a) / m


def empirical_selective_risk(
    losses: Sequence[float], accepted: Sequence[int | bool]
) -> float:
    """r̂(f,g|S_m) = (Σ ℓ_i g_i) / (Σ g_i) — invariant 1's conditional denominator.

    Risk is conditional on ANSWERING: the denominator is the accepted count, not m. An item
    routed to a human (g=0) is not counted as a model error."""
    if len(losses) != len(accepted):
        raise ValueError("losses and accepted must align")
    n_acc = sum(1 for a in accepted if a)
    if n_acc == 0:
        return 0.0  # nothing answered ⇒ no answering-error mass (vacuous, zero coverage)
    err = sum(l for l, a in zip(losses, accepted) if a)
    return err / n_acc


def _binom_cdf_le(n: int, k: int, b: float) -> float:
    """P(Bin(n, b) ≤ k) = Σ_{j=0}^{k} C(n,j) b^j (1−b)^{n−j}, computed in log-space via
    logsumexp for numerical stability at large n / tiny probabilities."""
    if b <= 0.0:
        return 1.0  # all mass at j=0 ≤ k
    if b >= 1.0:
        return 1.0 if k >= n else 0.0
    log_terms = []
    logb, log1mb = math.log(b), math.log1p(-b)
    for j in range(0, k + 1):
        log_comb = math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
        log_terms.append(log_comb + j * logb + (n - j) * log1mb)
    m = max(log_terms)
    return math.exp(m + math.log(sum(math.exp(t - m) for t in log_terms)))


def gascuel_caraux_bound(n: int, n_errors: int, delta: float) -> float:
    """B*(r̂, δ, S_m): the b solving Σ_{j=0}^{n_errors} C(n,j) b^j (1−b)^{n−j} = δ.

    This is the Clopper–Pearson upper confidence limit on the binomial rate given n_errors
    failures in n trials. P(Bin(n,b) ≤ n_errors) is strictly decreasing in b, so the root is
    unique; solved by bisection. Edge cases: n_errors ≥ n ⇒ the sum is 1 for all b, the bound
    is vacuous (return 1.0); n_errors = 0 ⇒ closed form b = 1 − δ^{1/n}."""
    if not (0.0 < delta < 1.0):
        raise ValueError("delta must be in (0, 1)")
    if n <= 0:
        raise ValueError("n must be >= 1")
    if n_errors >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        # cdf decreasing in b: if cdf(mid) > delta we need a larger b, else smaller.
        if _binom_cdf_le(n, n_errors, mid) > delta:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True, slots=True)
class BoundCall:
    """One SGR binary-search iteration's audit record. delta is δ/k (invariant 8)."""

    iteration: int
    theta: float
    n_accepted: int
    n_errors: int
    empirical_risk: float
    delta: float
    bound: float


@dataclass(frozen=True, slots=True)
class SGRResult:
    k: int
    theta: float
    bound: float
    coverage: float
    selective_risk: float
    feasible: bool
    audit: tuple[BoundCall, ...]


def sgr(
    confidences: Sequence[float],
    losses: Sequence[float],
    delta: float,
    r_star: float,
) -> SGRResult:
    """Algorithm 1. Returns the final iterate g_k, its bound b_k, and the per-iteration audit.

    Direction (matches lines 10–13): sort ascending by κ_f; larger threshold θ ⇒ fewer
    accepted ⇒ lower coverage and lower risk. We seek the smallest θ (max coverage) whose
    δ/k-level bound is still < r*. If b*_i < r*, try more coverage (z_max = z); else less
    (z_min = z)."""
    m = len(confidences)
    if m == 0:
        raise ValueError("sgr requires a non-empty sample")
    if len(losses) != m:
        raise ValueError("confidences and losses must align")
    if not (0.0 < delta < 1.0):
        raise ValueError("delta must be in (0, 1)")

    order = sorted(range(m), key=lambda i: confidences[i])
    conf_sorted = [confidences[i] for i in order]
    k = math.ceil(math.log2(m)) if m > 1 else 1
    per_iter_delta = delta / k

    z_min, z_max = 1, m
    audit: list[BoundCall] = []
    last: BoundCall | None = None
    for i in range(1, k + 1):
        z = math.ceil((z_min + z_max) / 2)
        theta = conf_sorted[z - 1]  # κ_f(x_z), 1-indexed
        accepted = [1 if confidences[j] >= theta else 0 for j in range(m)]
        n_acc = sum(accepted)
        n_err = int(round(sum(l for l, a in zip(losses, accepted) if a)))
        r_hat = empirical_selective_risk(losses, accepted)
        b = gascuel_caraux_bound(n_acc, n_err, per_iter_delta) if n_acc > 0 else 1.0
        call = BoundCall(i, theta, n_acc, n_err, r_hat, per_iter_delta, b)
        audit.append(call)
        last = call
        if b < r_star:
            z_max = z
        else:
            z_min = z

    assert last is not None
    accepted = [1 if confidences[j] >= last.theta else 0 for j in range(m)]
    return SGRResult(
        k=k,
        theta=last.theta,
        bound=last.bound,
        coverage=empirical_coverage(accepted),
        selective_risk=last.empirical_risk,
        feasible=last.bound < r_star,
        audit=tuple(audit),
    )
