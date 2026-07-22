"""Coverage telemetry — realized vs. target, overall and PER SEGMENT (Part 2, non-goals).

ACI gives MARGINAL coverage. Mohri & Hashimoto measure σ≈0.09 wander in realized factuality,
and under ECOA/Reg B a portfolio average masking a weak segment is not a defense. So coverage
is segmented (2-digit NAICS, state, business-age bucket) and the WORST segment is surfaced
loudly — never averaged away. Conditional guarantees are not claimed (Gibbs/Cherian/Candès
2024 is a named future dependency, not implemented).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SegmentCoverage:
    segment_key: str
    n: int
    realized_coverage: float  # automated / processed
    realized_marginal_miscoverage: float  # auto-and-wrong / processed (the guaranteed quantity)
    target_coverage: float

    @property
    def coverage_shortfall(self) -> float:
        return max(0.0, self.target_coverage - self.realized_coverage)


@dataclass(frozen=True, slots=True)
class CoverageReport:
    overall: SegmentCoverage
    by_segment: dict[str, SegmentCoverage]
    worst_segment_key: str  # lowest coverage — surfaced first, always
    worst_miscoverage_key: str  # highest marginal miscoverage — the guarantee's weak point


@dataclass
class _Acc:
    n: int = 0
    automated: int = 0
    auto_wrong: float = 0.0


def build_coverage_report(
    rows: Iterable[tuple[str, bool, float]],
    target_coverage: float,
) -> CoverageReport:
    """rows: (segment_key, automated, marginal_miscoverage_contribution). The third element is
    each field's contribution to marginal miscoverage — 1.0 if it was automated AND wrong, else
    0.0 (unknown-truth fields contribute 0 and are simply not counted as errors)."""
    segs: dict[str, _Acc] = {}
    overall = _Acc()
    for key, automated, miss in rows:
        a = segs.setdefault(key, _Acc())
        for acc in (a, overall):
            acc.n += 1
            acc.automated += 1 if automated else 0
            acc.auto_wrong += miss

    def mk(key: str, acc: _Acc) -> SegmentCoverage:
        cov = acc.automated / acc.n if acc.n else 0.0
        miscov = acc.auto_wrong / acc.n if acc.n else 0.0
        return SegmentCoverage(key, acc.n, cov, miscov, target_coverage)

    by_segment = {k: mk(k, a) for k, a in segs.items()}
    if not by_segment:
        raise ValueError("no rows to build a coverage report")
    worst_cov = min(by_segment, key=lambda k: by_segment[k].realized_coverage)
    worst_mis = max(by_segment, key=lambda k: by_segment[k].realized_marginal_miscoverage)
    return CoverageReport(
        overall=mk("__overall__", overall),
        by_segment=by_segment,
        worst_segment_key=worst_cov,
        worst_miscoverage_key=worst_mis,
    )
