"""Geifman's naive baseline — the thing the system must beat, and the entire argument.

Geifman & El-Yaniv 2017 §5.2 (verified against print): "the threshold to be the value that
maximizes coverage while keeping train error smaller than r*. For this simple baseline we
found that in over 50% of the cases (1000 random train/test splits), the bound r* was
violated over the test set, with a mean violation of 18% relative to the requested r*."

The naive rule sits the threshold RIGHT AT the boundary — the smallest θ whose TRAIN selective
risk is still below r*. With no finite-sample correction and no shift adjustment, its train
risk ≈ r*⁻, so on held-out data sampling noise alone pushes test risk over r* about half the
time; distribution shift pushes it over far more than half. SGR (conformal/sgr.py) fixes this
by thresholding on the Gascuel–Caraux bound B* < r* instead of r̂ < r*.

Reproducing this violation on the non-exchangeable stream is what justifies the whole system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..conformal.sgr import empirical_coverage, empirical_selective_risk


def naive_threshold(confidences: Sequence[float], losses: Sequence[float], r_star: float) -> float:
    """Smallest θ (⇒ maximal coverage) whose selective risk on this sample is < r*.

    Accept rule is κ_f(x) ≥ θ. Maximal coverage means the largest accept set: sort by
    confidence descending and take the largest prefix (top-j highest-confidence items) whose
    prefix selective risk is < r*; θ is that prefix's smallest accepted confidence. O(n log n).
    Threshold at a tie boundary accepts the whole tie group, matching the ≥ rule. Returns a θ
    strictly above every confidence (accept nothing, zero coverage) when nothing is feasible —
    the vacuous case Geifman's Algorithm-1 footnote 1 also allows."""
    if len(confidences) != len(losses):
        raise ValueError("confidences and losses must align")
    if not confidences:
        raise ValueError("empty sample")
    order = sorted(range(len(confidences)), key=lambda i: confidences[i], reverse=True)
    cum_err = 0
    best_theta: float | None = None
    for rank, i in enumerate(order, start=1):
        cum_err += losses[i]
        # Only evaluate at tie-group boundaries so the accept set is exactly {c ≥ conf[i]}.
        if rank < len(order) and confidences[order[rank]] == confidences[i]:
            continue
        if cum_err / rank < r_star:
            best_theta = confidences[i]  # larger prefix ⇒ smaller θ ⇒ more coverage
    if best_theta is not None:
        return best_theta
    return max(confidences) + 1e-9  # infeasible ⇒ accept nothing (vacuous)


def selective_risk_at(confidences: Sequence[float], losses: Sequence[float], theta: float) -> tuple[float, float]:
    """(selective_risk, coverage) when accepting κ_f(x) ≥ θ."""
    accepted = [1 if c >= theta else 0 for c in confidences]
    if sum(accepted) == 0:
        return 0.0, 0.0
    return empirical_selective_risk(losses, accepted), empirical_coverage(accepted)


@dataclass(frozen=True, slots=True)
class ViolationRun:
    calib_risk: float
    deploy_risk: float
    deploy_coverage: float
    theta: float
    violated: bool
    relative_violation: float  # (deploy_risk − r*)/r*, only meaningful when violated


@dataclass(frozen=True, slots=True)
class ViolationStudy:
    n_runs: int
    violation_rate: float
    mean_relative_violation: float  # over violating runs (Geifman reports ~0.18)
    runs: tuple[ViolationRun, ...]


def _run_once(
    confidences: Sequence[float],
    losses: Sequence[float],
    calib_idx: Sequence[int],
    deploy_idx: Sequence[int],
    r_star: float,
) -> ViolationRun:
    c_conf = [confidences[i] for i in calib_idx]
    c_loss = [losses[i] for i in calib_idx]
    d_conf = [confidences[i] for i in deploy_idx]
    d_loss = [losses[i] for i in deploy_idx]
    theta = naive_threshold(c_conf, c_loss, r_star)
    calib_risk, _ = selective_risk_at(c_conf, c_loss, theta)
    deploy_risk, deploy_cov = selective_risk_at(d_conf, d_loss, theta)
    violated = deploy_risk > r_star
    rel = (deploy_risk - r_star) / r_star if violated else 0.0
    return ViolationRun(calib_risk, deploy_risk, deploy_cov, theta, violated, rel)


def temporal_violation_study(
    confidences: Sequence[float],
    losses: Sequence[float],
    r_star: float,
    n_runs: int,
    window: int,
    rng,
) -> ViolationStudy:
    """Calibrate-then-deploy on adjacent arrival windows (the realistic policy), with a
    randomized start position per run to reproduce Geifman's split-to-split variance while
    honoring arrival order — the deployment window is always the one that arrives next.

    On a shifting stream the deployment window is drawn from a later (less familiar)
    distribution than the calibration window, so a boundary-sitting threshold under-covers.
    On the i.i.d. ablation the two windows are exchangeable and the rate falls toward the
    ~50% sampling floor."""
    n = len(confidences)
    if 2 * window > n:
        raise ValueError("stream too short for two adjacent windows of this size")
    runs = []
    max_start = n - 2 * window
    for _ in range(n_runs):
        start = rng.randint(0, max_start)
        calib_idx = range(start, start + window)
        deploy_idx = range(start + window, start + 2 * window)
        runs.append(_run_once(confidences, losses, list(calib_idx), list(deploy_idx), r_star))
    violated = [r for r in runs if r.violated]
    rate = len(violated) / n_runs
    mean_rel = sum(r.relative_violation for r in violated) / len(violated) if violated else 0.0
    return ViolationStudy(n_runs, rate, mean_rel, tuple(runs))
