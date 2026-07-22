"""Loop B — case decision. INSTRUMENTED, NOT GUARANTEED. Does NOT inherit Loop A.

aggregate fields → derived metrics → case decision. Ground truth (default / no-default) arrives
in months, and ONLY for approved loans — the rejection-inference / selective-labels problem no
paper in this set addresses. Therefore:

  - Loop B does NOT run the ACI update. Any path that would close this loop raises
    NotImplementedError citing Gibbs & Candès §7 (delayed and batched response named as open)
    and the rejection-inference problem.
  - Loop B does NOT claim coverage. It emits metrics only.
  - Loop B does NOT inherit from FieldLoop — they are not the same thing. A case decision is a
    composition of guaranteed field outputs and UNguaranteed derived metrics; the composition
    itself carries no distribution-free guarantee.

The RiskTier decision here is deterministic given the (possibly reviewer-corrected) field
values and derived metrics; its provenance chain is preserved for the examiner, but its
confidence is explicitly not modeled (propagation.py is unsolved).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..derived.metrics import ADBInputs, DSCRInputs, UndefinedMetricError, adb_ratio, dscr
from ..domain.types import RiskTier, Segment


class CaseLoopGuaranteeError(NotImplementedError):
    """Raised by any attempt to run the ACI update or claim coverage in Loop B."""


@dataclass(frozen=True, slots=True)
class CaseMetrics:
    dscr: Decimal | None
    adb_ratio: Decimal | None
    undefined_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseDecision:
    case_id: str
    segment: Segment
    risk_tier: RiskTier
    metrics: CaseMetrics
    n_fields_automated: int
    n_fields_routed: int
    guaranteed: bool = False  # ALWAYS False — Loop B makes no coverage guarantee


@dataclass
class CaseDecisionThresholds:
    dscr_approve: Decimal = Decimal("1.25")
    dscr_decline: Decimal = Decimal("1.0")
    adb_approve: Decimal = Decimal("1.5")


def compute_case_metrics(
    net_income: Decimal,
    depreciation: Decimal,
    total_debt_service: Decimal,
    avg_daily_balance: Decimal,
    monthly_debt_service: Decimal,
) -> CaseMetrics:
    undefined: list[str] = []
    try:
        d = dscr(DSCRInputs(net_income, depreciation, total_debt_service))
    except UndefinedMetricError as exc:
        d, _ = None, undefined.append(str(exc))
    try:
        a = adb_ratio(ADBInputs(avg_daily_balance, monthly_debt_service))
    except UndefinedMetricError as exc:
        a, _ = None, undefined.append(str(exc))
    return CaseMetrics(dscr=d, adb_ratio=a, undefined_reasons=tuple(undefined))


def decide_case(
    case_id: str,
    segment: Segment,
    metrics: CaseMetrics,
    n_fields_automated: int,
    n_fields_routed: int,
    thresholds: CaseDecisionThresholds | None = None,
    any_field_routed_unresolved: bool = False,
) -> CaseDecision:
    """Emit a RiskTier. This is INSTRUMENTED only: no coverage is claimed, no confidence is
    propagated (propagation.py is unsolved). If any field is still routed/unresolved, or a
    metric is undefined, the case itself routes to REVIEW rather than ruling on partial
    evidence."""
    th = thresholds or CaseDecisionThresholds()
    if any_field_routed_unresolved or metrics.dscr is None:
        tier = RiskTier.REVIEW
    elif metrics.dscr >= th.dscr_approve and (metrics.adb_ratio or Decimal(0)) >= th.adb_approve:
        tier = RiskTier.APPROVE
    elif metrics.dscr < th.dscr_decline:
        tier = RiskTier.DECLINE
    else:
        tier = RiskTier.REVIEW
    return CaseDecision(
        case_id=case_id,
        segment=segment,
        risk_tier=tier,
        metrics=metrics,
        n_fields_automated=n_fields_automated,
        n_fields_routed=n_fields_routed,
    )


def update_coverage_from_case_outcome(*_args, **_kwargs) -> None:
    """FORBIDDEN. Closing the case-level loop with an ACI update is not supported: ground truth
    is delayed by months and observed only for approved loans (rejection inference / selective
    labels), which Gibbs & Candès §7 names as open."""
    raise CaseLoopGuaranteeError(
        "Loop B must not run the ACI update or claim coverage. Case-level ground truth is "
        "delayed and batched (Gibbs & Candès §7, named open) and subject to rejection "
        "inference — only approved loans are ever labeled. Emit metrics only."
    )
