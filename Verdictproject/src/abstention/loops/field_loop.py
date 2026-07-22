"""Loop A — field extraction, the GUARANTEED loop (Part 2).

extract → score conformity → calibrate → route or accept → observe reviewer correction →
update α_t. ACI applies here because reviewer corrections give fast, near-complete feedback on
routed items. This is where the contribution lives.

The guarantee is over the CONFORMITY SCORE and holds for any extractor producing one (Part 5
non-goal: a real LLM extractor is stubbed). Here the nonconformity score is s = 1 − calibrated
confidence; ACI maintains α_t and the threshold τ_t = Q̂_t(1−α_t) over a rolling window of
observed scores; a Path-2 field is automated iff s ≤ τ_t (CONFORMITY_SCORE_WITHIN_THRESHOLD)
AND the Bayes rule accepts it (calibrated confidence ≥ instance reviewer accuracy). Everything
else routes, consuming reviewer budget.

Honest scope (Gibbs §7; synthesis): ACI needs Y_t each step, but truth is revealed only on
routed items plus an audited fraction of accepts. The loop updates α_t on exactly those
observed items. The selective-labels bias this induces is named, not hidden — and it is why
Loop B (case_loop) refuses to run ACI at all.

DEGRADED items (Part 6): a missing field, failed extraction, oracle exception, or absent
confidence degrades THAT item to a routed DegradedItem with the correct reason — EXCLUDED from
the conformity distribution (it must not corrupt α_t) but INCLUDED in budget burn.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..conformal.aci import ACIState
from ..deferral.budget import ReviewerBudget
from ..deferral.reviewer_model import ReviewerAccuracyModel
from ..domain.models import (
    DecisionAction,
    DegradedItem,
    FieldDecision,
    Path1Absent,
    Path2Scored,
    Path3Contradicted,
)
from ..domain.taxonomy import AcceptReason, RouteReason
from ..domain.types import FieldType, Segment
from ..forecast.automation import AutomationForecast, ForecastScore, score_forecast


@dataclass(frozen=True, slots=True)
class FieldInput:
    """One field presented to the loop, with ground truth held aside for feedback/scoring."""

    field_type: FieldType
    calibrated_confidence: float | None  # None ⇒ NO_CONFIDENCE_AVAILABLE (never defaulted)
    true_error: int  # ground truth: 1 if the extracted value is actually wrong
    segment: Segment
    reviewer_id: str = "rev-1"
    forced_path: str = "PATH_2"  # PATH_1 / PATH_3 for absent / contradicted fields
    absent_reason: RouteReason = RouteReason.FIELD_ABSENT_FROM_DOCUMENT


@dataclass(frozen=True, slots=True)
class FieldRecord:
    field_type: FieldType
    action: DecisionAction
    reason: object
    path: str
    nonconformity: float | None
    observed: bool
    was_error: int | None
    segment: Segment


@dataclass
class BatchResult:
    batch_id: str
    forecast: AutomationForecast
    records: list[FieldRecord]
    n_fields: int
    n_automated: int
    n_routed: int
    n_degraded: int
    realized_automation_rate: float
    realized_marginal_miscoverage: float  # GUARANTEED quantity: auto-and-wrong / all fields
    realized_conditional_selective_risk: float  # reported, not guaranteed: auto-and-wrong / automated
    realized_coverage: float
    forecast_score: ForecastScore
    alpha_t: float
    tau_t: float


@dataclass
class FieldLoopConfig:
    r_star: float = 0.05
    alpha: float = 0.10  # ACI miscoverage target ⇒ 1−α coverage on the field layer
    gamma: float = 0.005
    quantile_window: int = 500
    audit_rate: float = 1.0  # fraction of accepts whose truth is observed (1.0 for evaluation)
    min_calibration: int = 40  # route-conservatively until this many scores are observed
    reviewer_id: str = "rev-1"
    budget_per_batch: int = 10_000


class FieldLoop:
    def __init__(
        self,
        config: FieldLoopConfig,
        reviewer_model: ReviewerAccuracyModel,
        rng,
    ) -> None:
        self.config = config
        self.reviewer_model = reviewer_model
        self.rng = rng
        self.aci = ACIState(alpha_target=config.alpha, gamma=config.gamma)
        self._scores: deque[float] = deque(maxlen=config.quantile_window)
        # F2 — held-out forecast basis: the PREVIOUS batch's inputs. The forecast for batch B
        # is formed from data the forecaster has already seen (batches < B), then scored on B.
        # Gibbs & Candès 2021 §2: the prediction for step t uses {(X_r,Y_r)}_{1≤r≤t−1} and is
        # scored on the unseen (X_t,Y_t). A forecast computed on the batch it is scored on
        # (the old behavior) is a recompute, not a prediction, and can never miss.
        self._forecast_basis: list[FieldInput] = []

    # ---- threshold from ACI state -----------------------------------------------------
    def current_tau(self) -> float:
        """τ_t = Q̂_s(α_t): the α_t-quantile of observed nonconformity scores. Accept iff
        s = 1 − conf ≤ τ_t.

        The level is α_t, NOT 1−α_t: in selective prediction the always-covering action is to
        ABSTAIN (route to the human), which inverts the usual prediction-set direction. The
        feedback must be negative — when miscoverage err rises above the target, the ACI
        recursion lowers α_t, which lowers τ_t, which accepts fewer (higher-confidence) items,
        which drives err back down. With the 1−α_t level the sign would flip and the loop
        would accept MORE as it errs MORE. Before enough scores accumulate, τ_t = 0 ⇒ nothing
        is auto-accepted (route conservatively rather than guess)."""
        if len(self._scores) < self.config.min_calibration:
            return 0.0
        ordered = sorted(self._scores)
        level = min(max(self.aci.alpha, 0.0), 1.0)
        idx = min(len(ordered) - 1, int(level * (len(ordered) - 1)))
        return ordered[idx]

    def _bayes_accepts(self, field_type: FieldType, conf: float, reviewer_id: str) -> bool:
        acc = self.reviewer_model.expected_accuracy(field_type, reviewer_id)
        return conf >= acc

    def _would_automate(self, fi: FieldInput, tau: float) -> bool:
        if fi.forced_path != "PATH_2" or fi.calibrated_confidence is None:
            return False
        s = 1.0 - fi.calibrated_confidence
        return s <= tau and self._bayes_accepts(fi.field_type, fi.calibrated_confidence, fi.reviewer_id)

    # ---- forecast BEFORE processing ---------------------------------------------------
    def forecast(self, batch_id: str, batch: Sequence[FieldInput], segment: Segment | None = None) -> AutomationForecast:
        """Predict batch B's automation rate from HELD-OUT prior data (the previous batch),
        never from B itself (F2). The threshold τ is likewise fit only on prior scores. Under
        distribution shift the prior-batch automation rate is an imperfect predictor of B's, so
        predicted ≠ realized is reachable and `automation_missed` can fire. The first batch has
        no history; it falls back to the batch (predicted ≡ realized only there)."""
        tau = self.current_tau()
        basis = self._forecast_basis if self._forecast_basis else batch
        pred = (sum(1 for fi in basis if self._would_automate(fi, tau)) / len(basis)) if basis else 0.0
        return AutomationForecast(
            batch_id=batch_id,
            segment=segment,
            n_fields=len(batch),
            predicted_automation_rate=pred,
            target_marginal_miscoverage=self.config.alpha,
            predicted_coverage=1.0 - self.config.alpha,
            threshold_tau=tau,
        )

    # ---- process the batch with the forecast's frozen τ -------------------------------
    def process_batch(
        self, batch_id: str, batch: Sequence[FieldInput], segment: Segment | None = None
    ) -> BatchResult:
        forecast = self.forecast(batch_id, batch, segment)
        tau = forecast.threshold_tau
        budget = ReviewerBudget(total=self.config.budget_per_batch)
        records: list[FieldRecord] = []
        automated = routed = degraded = 0
        accept_errors = accept_observed = 0
        # ACI feedback: (nonconformity score, miscoverage event). Miscoverage err_t =
        # 1[accepted ∧ wrong]; a routed item is covered by the human ⇒ err_t = 0.
        aci_scores: list[float] = []
        aci_errs: list[int] = []

        for fi in batch:
            # Path 1 / Path 3 route unconditionally; never enter the conformity distribution.
            if fi.forced_path == "PATH_1":
                routed += 1
                budget.spend()
                records.append(FieldRecord(fi.field_type, DecisionAction.ROUTE, fi.absent_reason, "PATH_1", None, False, None, fi.segment))
                continue
            if fi.forced_path == "PATH_3":
                routed += 1
                budget.spend()
                records.append(FieldRecord(fi.field_type, DecisionAction.ROUTE, RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT, "PATH_3", None, False, None, fi.segment))
                continue

            # Degraded: no confidence ⇒ route, excluded from calibration, included in burn.
            if fi.calibrated_confidence is None:
                degraded += 1
                routed += 1
                budget.spend()
                records.append(FieldRecord(fi.field_type, DecisionAction.ROUTE, RouteReason.NO_CONFIDENCE_AVAILABLE, "DEGRADED", None, False, None, fi.segment))
                continue

            s = 1.0 - fi.calibrated_confidence
            automate = self._would_automate(fi, tau)
            if automate:
                automated += 1
                reason = AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD
                # Observe truth on an audited fraction of accepts (selective-labels honesty).
                observed = self.rng.random() < self.config.audit_rate
                was_err = fi.true_error if observed else None
                if observed:
                    accept_observed += 1
                    accept_errors += fi.true_error
                    aci_scores.append(s)
                    aci_errs.append(fi.true_error)  # accepted ∧ wrong ⇒ miscoverage
                records.append(FieldRecord(fi.field_type, DecisionAction.ACCEPT, reason, "PATH_2", s, observed, was_err, fi.segment))
            else:
                routed += 1
                budget.spend()
                if s > tau:
                    reason = RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD
                else:
                    reason = RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY
                # Routed item: near-complete reviewer feedback, but it is COVERED by the human,
                # so its miscoverage event is 0. Its score still informs the quantile window.
                aci_scores.append(s)
                aci_errs.append(0)
                records.append(FieldRecord(fi.field_type, DecisionAction.ROUTE, reason, "PATH_2", s, True, fi.true_error, fi.segment))

        # ACI update on observed items in arrival order: err_t = 1[accepted ∧ wrong].
        for s, e in zip(aci_scores, aci_errs):
            self._scores.append(s)
            self.aci = self.aci.update(err=int(e))

        n = len(batch)
        realized_auto = automated / n if n else 0.0
        # GUARANTEED (marginal): auto-and-wrong over ALL fields, scaled by the audit rate so it
        # estimates the true rate when not every accept is observed.
        observed_auto_wrong = accept_errors
        marginal_miscov = (observed_auto_wrong / accept_observed * realized_auto) if accept_observed else 0.0
        # REPORTED (conditional): error rate among automated fields with observed truth.
        conditional_risk = accept_errors / accept_observed if accept_observed else 0.0
        realized_cov = automated / n if n else 0.0
        fscore = score_forecast(
            forecast,
            realized_automation_rate=realized_auto,
            realized_marginal_miscoverage=marginal_miscov,
            realized_conditional_selective_risk=conditional_risk,
            realized_coverage=realized_cov,
            n_observed_accepts=accept_observed,
        )
        # This batch becomes the held-out forecast basis for the NEXT batch (F2).
        self._forecast_basis = list(batch)
        return BatchResult(
            batch_id=batch_id,
            forecast=forecast,
            records=records,
            n_fields=n,
            n_automated=automated,
            n_routed=routed,
            n_degraded=degraded,
            realized_automation_rate=realized_auto,
            realized_marginal_miscoverage=marginal_miscov,
            realized_conditional_selective_risk=conditional_risk,
            realized_coverage=realized_cov,
            forecast_score=fscore,
            alpha_t=self.aci.alpha,
            tau_t=tau,
        )
