"""End-to-end disparate-impact measurement (invariant 10).

Mozannar & Sontag §6.5 (verified): a fair classifier (discrimination 0.226) composed with a
fair expert (0.03) via the confidence-score baseline produced discrimination 0.449 — the
composition roughly DOUBLED it, and a biased expert made things better. "fairness does not
compose (Dwork & Ilvento, 2018)." No component-wise argument survives.

Therefore disparate impact is measured ONLY on the composed extraction → routing → reviewer →
decision output, never component-wise. Here discrimination is the gap in false-positive rate
(an adverse-decision analogue) across a segment axis (2-digit NAICS, state, business-age
bucket). The worst segment is surfaced explicitly (non-goal: marginal coverage may mask a weak
segment; under ECOA/Reg B a portfolio average is not a defense).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class DisparateImpactReport:
    fpr_by_group: dict[str, float]
    max_gap: float
    worst_group: str  # highest FPR — the most adversely treated segment
    best_group: str
    n_by_group: dict[str, int]


def _fpr(decisions: Sequence[tuple[bool, bool]]) -> float | None:
    """FP / negatives, where each item is (decided_positive, truth_positive). A "positive"
    decision is the adverse action; FPR is the rate of adverse decisions on true negatives.
    Returns None when a group has no negatives (undefined)."""
    negatives = [d for d in decisions if not d[1]]
    if not negatives:
        return None
    fp = sum(1 for decided, truth in negatives if decided)
    return fp / len(negatives)


def end_to_end_disparate_impact(
    outcomes_by_group: Mapping[str, Sequence[tuple[bool, bool]]]
) -> DisparateImpactReport:
    """Compute per-group FPR on COMPOSED (decided_positive, truth_positive) outcomes and the
    worst gap. Groups with undefined FPR (no negatives) are excluded from the gap."""
    fpr = {g: _fpr(d) for g, d in outcomes_by_group.items()}
    defined = {g: v for g, v in fpr.items() if v is not None}
    if not defined:
        raise ValueError("no group has any negatives; FPR gap is undefined")
    worst = max(defined, key=lambda g: defined[g])
    best = min(defined, key=lambda g: defined[g])
    return DisparateImpactReport(
        fpr_by_group=defined,
        max_gap=defined[worst] - defined[best],
        worst_group=worst,
        best_group=best,
        n_by_group={g: len(d) for g, d in outcomes_by_group.items()},
    )
