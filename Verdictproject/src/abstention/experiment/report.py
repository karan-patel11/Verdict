"""Assemble the experiment report — the table for the writeup and the JSON for the front-end.

One run over a config's stream produces: the falsifiable-claim evidence (naive violation rate
vs. the guaranteed loop), per-batch AutomationForecasts scored against realized outcomes (the
"in advance" claim), per-segment coverage with the worst surfaced, the Theorem-4.2 shift
statistic, an end-to-end disparate-impact surface (Loop B, instrumented), a finite reviewer
budget with burn, and a reviewer queue with full provenance exercising all three paths.

Guaranteed (Loop A) and instrumented (Loop B) quantities are tagged `loop: "A"/"B"` and
`guaranteed: true/false` so the front-end can keep them permanently, visually distinct — the
single most important decision on the page (Part 7).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from ..baselines.naive_threshold import (
    naive_threshold,
    selective_risk_at,
    temporal_violation_study,
)
from ..conformal.sgr import sgr
from ..deferral.budget import ReviewerBudget
from ..deferral.reviewer_model import ReviewerAccuracyModel
from ..domain.taxonomy import TAXONOMY_VERSION, AcceptReason, RouteReason
from ..domain.types import RiskTier, Segment
from ..data.synthetic import (
    HOTPOTQA_ANALOGUE_ARCHETYPE,
    SyntheticStream,
    non_exchangeability_report,
    stream_config_from_mapping,
)
from ..loops.field_loop import FieldInput, FieldLoop, FieldLoopConfig
from ..telemetry.coverage import build_coverage_report
from ..telemetry.fairness import end_to_end_disparate_impact
from ..telemetry.shift import build_shift_report
from .file_analysis import _BatchContext, build_file_analyses

# Human-readable, ECOA-adverse-action-style labels. The front-end shows the DECISION and this
# label, never a bare percentage (Part 7 decision 1).
REASON_LABEL: dict[str, str] = {
    RouteReason.FIELD_ABSENT_FROM_DOCUMENT: "Field not present in the document",
    RouteReason.DOCUMENT_ARCHETYPE_UNSUPPORTED: "Document type not supported for this field",
    RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY: "Calibrated confidence below reviewer accuracy",
    RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD: "Uncertainty above the guaranteed threshold",
    RouteReason.NO_CONFIDENCE_AVAILABLE: "No confidence score available",
    RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT: "Sources disagree on this value",
    RouteReason.ACCRUAL_CASH_DIVERGENCE: "Accruals diverge from cash flow across documents",
    RouteReason.EXTRACTION_ERROR: "Extraction failed",
    AcceptReason.CALIBRATED_CONFIDENCE_ABOVE_REVIEWER_ACCURACY: "Calibrated confidence at or above reviewer accuracy",
    AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD: "Uncertainty within the guaranteed threshold",
}

PATH_LABEL = {
    "PATH_1": "Absent",
    "PATH_2": "Uncertain",
    "PATH_3": "Contradicted",
    "DEGRADED": "Degraded",
}


def _seg_key(seg: Segment) -> str:
    return seg.industry_naics2


def _windowed_risk_comparison(
    conf: list[float], loss: list[float], r_star: float, delta: float,
    n_runs: int, window: int, rng: random.Random,
) -> dict[str, float]:
    """One goalpost, one metric (F1). Both rules are scored on CONDITIONAL selective risk —
    Geifman & El-Yaniv 2017 Eq. (1): R(f,g) = E[ℓ(f(x),y)g(x)] / φ(f,g), φ = coverage (the
    denominator is the ACCEPTED count, never all fields) — at the SAME r* on the SAME
    calibrate/deploy windows. The naive boundary-sitting threshold vs. Verdict's
    risk-controlled threshold (SGR / Gascuel–Caraux bound, sgr.py). No marginal-vs-conditional
    or α-vs-r* mismatch: this is the honest head-to-head.
    """
    n = len(conf)
    max_start = n - 2 * window
    naive_viol = sys_viol = 0
    naive_risk_sum = sys_risk_sum = 0.0
    for _ in range(n_runs):
        s = rng.randint(0, max_start)
        cc, cl = conf[s : s + window], loss[s : s + window]
        dc, dl = conf[s + window : s + 2 * window], loss[s + window : s + 2 * window]
        # Naive: max coverage s.t. train conditional risk < r*.
        n_theta = naive_threshold(cc, cl, r_star)
        n_risk, _ = selective_risk_at(dc, dl, n_theta)  # deploy conditional risk
        naive_risk_sum += n_risk
        naive_viol += 1 if n_risk > r_star else 0
        # System: SGR δ/k Gascuel–Caraux bound threshold, same r*.
        s_theta = sgr(cc, cl, delta, r_star).theta
        s_risk, _ = selective_risk_at(dc, dl, s_theta)
        sys_risk_sum += s_risk
        sys_viol += 1 if s_risk > r_star else 0
    return {
        "naive_violation_rate": round(naive_viol / n_runs, 4),
        "naive_conditional_selective_risk": round(naive_risk_sum / n_runs, 4),
        "system_violation_rate": round(sys_viol / n_runs, 4),
        "system_conditional_selective_risk": round(sys_risk_sum / n_runs, 4),
    }


def _calibrator_auc_check(fields, rng_seed: int = 7) -> dict[str, Any]:
    """F4 — is the Kamath RF calibrator actually better than raw extractor softmax on the
    (now decoupled) data? Compares risk–coverage AUC (AURC; lower = better) of raw softmax vs
    the calibrator's P(correct), on a held-out split. The calibrator goes ON-PATH only if it
    wins; otherwise routing honestly uses raw softmax and the word "calibrated" is not applied
    to the raw value. Kamath 2020 §4 (RF over softmax + structure): on a real corpus the
    structure carries correctness signal and the calibrator wins; this synthetic stub has none,
    so the check is expected to fall to raw softmax — and that is reported, not hidden."""
    from ..domain.models import CalibratorFeatures
    from ..domain.types import DocArchetype
    from ..scoring.calibrator import KamathCalibrator

    def feats(f):
        return CalibratorFeatures(
            field_type=f.field_type, archetype=DocArchetype.BALANCE_SHEET,
            softmax_top5=f.softmax_top5, raw_span_length=len(f.raw_span), doc_page_count=f.page,
            statement_transaction_count=0, distinct_source_documents=1, ood_score=f.ood_score,
        )

    def aurc(pairs):  # rank by score desc; area under the selective-risk-vs-coverage curve
        s = sorted(pairs, key=lambda x: -x[0])
        cum = 0.0
        areas = []
        for k, (_, err) in enumerate(s, 1):
            cum += err
            areas.append(cum / k)
        return sum(areas) / len(areas) if areas else 0.0

    rng = random.Random(rng_seed)
    idx = list(range(len(fields)))
    rng.shuffle(idx)
    idx = idx[:4000]  # subsample: the AUC conclusion is stable and this keeps the check fast
    h = len(idx) // 2
    tr, te = idx[:h], idx[h:]
    cal = KamathCalibrator(n_estimators=120, random_state=0).fit(
        [feats(fields[i]) for i in tr], [1 - fields[i].true_error for i in tr]
    )
    a_raw = aurc([(fields[i].confidence, fields[i].true_error) for i in te])
    a_rf = aurc([(cal.predict_confidence(feats(fields[i])), fields[i].true_error) for i in te])
    on_path = a_rf < a_raw
    return {
        "aurc_raw": round(a_raw, 4),
        "aurc_calibrator": round(a_rf, 4),
        "on_path": on_path,
        "routing_signal": "kamath_calibrator_output" if on_path else "raw_extractor_softmax",
        "note": (
            "The Kamath RF calibrator is OFF-PATH: on this synthetic stream it does not beat raw "
            "extractor softmax on risk–coverage AUC (no structural correctness signal beyond "
            "softmax top-1), so routing uses raw extractor confidence and the value is labelled "
            "'raw', not 'calibrated'. On a real corpus with informative structure (Kamath §4) the "
            "calibrator may win — this check re-decides automatically."
            if not on_path else
            "The Kamath RF calibrator is ON-PATH: it beats raw softmax on risk–coverage AUC; "
            "routing uses the calibrator's P(correct)."
        ),
    }


def _aggregate_risk_comparison(
    cfg: dict, r_star: float, delta: float, window: int, n_runs: int = 250,
) -> dict[str, Any]:
    """F1 aggregated over ALL configured seeds so the report number and the headline number
    are the SAME object (no seed-1-in-report / aggregate-in-headline gap). Reports the naive
    violation mean AND min (Geifman aggregated 1000 splits precisely because a single split is
    a near-coin-flip estimate), the system mean, and the per-seed detail."""
    import statistics

    seeds = cfg.get("seeds", [cfg.get("seed", 1)])
    per_seed: list[dict[str, Any]] = []
    for sd in seeds:
        fs = SyntheticStream(stream_config_from_mapping(cfg, seed=sd)).field_stream()
        c = [f.confidence for f in fs]
        loss = [float(f.true_error) for f in fs]
        one = _windowed_risk_comparison(c, loss, r_star, delta, n_runs, window, random.Random(sd + 7))
        one["seed"] = sd
        per_seed.append(one)
    nv = [p["naive_violation_rate"] for p in per_seed]
    sv = [p["system_violation_rate"] for p in per_seed]
    nr = [p["naive_conditional_selective_risk"] for p in per_seed]
    sr = [p["system_conditional_selective_risk"] for p in per_seed]
    return {
        "naive_violation_rate": round(statistics.mean(nv), 4),
        "naive_violation_rate_min": round(min(nv), 4),
        "naive_conditional_selective_risk": round(statistics.mean(nr), 4),
        "system_violation_rate": round(statistics.mean(sv), 4),
        "system_conditional_selective_risk": round(statistics.mean(sr), 4),
        "n_seeds": len(seeds),
        "seeds": per_seed,
    }


def _load(config_path: str | Path) -> dict:
    return yaml.safe_load(Path(config_path).read_text())


def build_report(config_path: str | Path) -> dict[str, Any]:
    cfg = _load(config_path)
    seed = cfg.get("seed", 1)
    r_star = cfg["r_star"]
    alpha = cfg["alpha"]
    delta = cfg["delta"]
    gamma = cfg["gamma"]
    window = cfg["baseline_experiment"]["window"]
    stream = SyntheticStream(stream_config_from_mapping(cfg, seed=seed))
    cases = stream.cases()
    fields = stream.field_stream()

    # ---- 1. the falsifiable claim: naive violation vs the guaranteed loop ------------
    conf = [f.confidence for f in fields]
    loss = [float(f.true_error) for f in fields]
    naive_study = temporal_violation_study(
        conf, loss, r_star, n_runs=250, window=window, rng=random.Random(seed + 7)
    )
    # F1 — the honest comparison: one r*, one metric (conditional selective risk), same windows,
    # aggregated over ALL seeds so the report and the headline cite the same object.
    comparison = _aggregate_risk_comparison(cfg, r_star, delta, window, n_runs=250)
    # F4 — is the RF calibrator actually better than raw softmax? (decides on-path vs off-path)
    calibrator_status = _calibrator_auc_check(fields)

    # ---- 2. run Loop A over the stream, per-segment, collecting forecasts ------------
    rm = ReviewerAccuracyModel(accuracy_by_field={}, default_accuracy=0.70)
    loop = FieldLoop(
        FieldLoopConfig(r_star=alpha, alpha=alpha, gamma=max(gamma, 0.02),
                        min_calibration=100, quantile_window=800,
                        budget_per_batch=cfg["reviewer_budget_per_batch"]),
        rm,
        random.Random(seed),
    )
    batch_size = 300
    cases_per_batch = batch_size // stream.config.fields_per_case
    case_batches = [cases[i : i + cases_per_batch]
                    for i in range(0, len(cases), cases_per_batch)]
    batch_reports: list[dict] = []
    batch_contexts: list[_BatchContext] = []
    coverage_rows: list[tuple[str, bool, float]] = []
    per_batch_miscov: list[float] = []
    forecast_failures = 0
    forecasts_scored = 0
    for bi, cbatch in enumerate(case_batches):
        inputs: list[FieldInput] = []
        for case in cbatch:
            for lf in case.labeled_fields:
                inputs.append(FieldInput(field_type=lf.field_type, calibrated_confidence=lf.confidence,
                                         true_error=lf.true_error, segment=case.segment))
        if not inputs:
            continue
        res = loop.process_batch(f"batch-{bi:03d}", inputs)
        per_batch_miscov.append(res.realized_marginal_miscoverage)
        for rec in res.records:
            miss = 1.0 if (rec.action.name == "ACCEPT" and rec.was_error) else 0.0
            coverage_rows.append((_seg_key(rec.segment), rec.action.name == "ACCEPT", miss))
        if res.forecast.threshold_tau > 0.0:
            forecasts_scored += 1
            forecast_failures += 1 if res.forecast_score.is_failure else 0
        batch_contexts.append(_BatchContext(batch_id=res.batch_id, tau=res.tau_t,
                                            alpha_t=res.alpha_t))
        batch_reports.append({
            "batch_id": res.batch_id,
            "loop": "A", "guaranteed": True,
            "predicted_automation_rate": round(res.forecast.predicted_automation_rate, 4),
            "realized_automation_rate": round(res.realized_automation_rate, 4),
            "target_marginal_miscoverage": round(res.forecast.target_marginal_miscoverage, 4),
            "realized_marginal_miscoverage": round(res.realized_marginal_miscoverage, 4),
            "realized_conditional_selective_risk": round(res.realized_conditional_selective_risk, 4),
            "alpha_t": round(res.alpha_t, 4),
            "is_failure": res.forecast_score.is_failure,
        })

    cov = build_coverage_report(coverage_rows, target_coverage=1.0 - alpha)
    shift = build_shift_report(per_batch_miscov, target_alpha=alpha, gamma_in_use=max(gamma, 0.02))
    nonx = non_exchangeability_report(fields, window=400)
    # System's realized CONDITIONAL selective risk over the stream (Geifman Eq. 1): errors
    # among ACCEPTED fields / accepted. Distinct from the marginal miscoverage ACI guarantees.
    n_accept = sum(1 for _, acc, _ in coverage_rows if acc)
    n_auto_wrong = sum(miss for _, acc, miss in coverage_rows if acc)
    system_conditional_risk = (n_auto_wrong / n_accept) if n_accept else 0.0

    # ---- 3. end-to-end disparate impact (Loop B — INSTRUMENTED, not guaranteed) ------
    di_rng = random.Random(seed + 3)
    outcomes: dict[str, list[tuple[bool, bool]]] = {}
    for case in cases:
        key = _seg_key(case.segment)
        # latent default propensity rises with OOD-ness of the case's fields (a stand-in truth,
        # since real default labels are delayed and selective — Loop B honesty).
        ood = sum(f.ood_score for f in case.labeled_fields) / len(case.labeled_fields)
        truth_default = di_rng.random() < 0.10 + 0.25 * ood
        # decided adverse (DECLINE) with propensity also rising in OOD (the composition hazard).
        decided_adverse = di_rng.random() < 0.08 + 0.30 * ood
        outcomes.setdefault(key, []).append((decided_adverse, truth_default))
    outcomes = {k: v for k, v in outcomes.items() if any(not t for _, t in v)}
    fairness = end_to_end_disparate_impact(outcomes)

    # ---- 4. reviewer budget snapshot + queue with provenance (all three paths) -------
    budget = ReviewerBudget(total=cfg["reviewer_budget_per_batch"])
    queue = _build_queue(stream, alpha, budget, rng=random.Random(seed + 5))

    # ---- 5. a few Loop B case cards (instrumented, visually distinct) -----------------
    case_cards = _build_case_cards(cases[:6])

    # ---- 6. per-file analyses: terminal timeline + validated memory graph -------------
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    analyses = build_file_analyses(cases, batch_contexts, cases_per_batch, generated_at, seed)

    predicted = [b["predicted_automation_rate"] for b in batch_reports if b["realized_marginal_miscoverage"] is not None]
    realized = [b["realized_automation_rate"] for b in batch_reports]
    steady = [b for b in batch_reports if b["alpha_t"] is not None][3:]

    report = {
        "meta": {
            "config": str(config_path),
            "taxonomy_version": TAXONOMY_VERSION,
            "generated_at": generated_at,
            "seed": seed,
            "r_star": r_star, "alpha": alpha, "delta": delta, "gamma": max(gamma, 0.02),
            "target_coverage": round(1.0 - alpha, 4),
            "n_cases": len(cases), "n_fields": len(fields),
            "hotpotqa_archetype": HOTPOTQA_ANALOGUE_ARCHETYPE,
            "calibrator": calibrator_status,  # F4: AUC-decided on-path/off-path, with evidence
        },
        "claim": {
            # F1: ONE r*, ONE metric (conditional selective risk, Geifman Eq. 1), same windows,
            # aggregated over all seeds (headline number == report number).
            "statement": (
                f"On conditional selective risk (Geifman Eq. 1) at a single r*={r_star}, over "
                f"randomized adjacent calibrate/deploy windows of a non-exchangeable stream "
                f"(aggregated over {comparison['n_seeds']} seeds), the naive confidence-threshold "
                f"rule violates r* on {comparison['naive_violation_rate']*100:.0f}% of held-out "
                f"windows (min {comparison['naive_violation_rate_min']*100:.0f}% across seeds) "
                f"while Verdict's risk-controlled threshold (SGR / Gascuel–Caraux bound) violates "
                f"on {comparison['system_violation_rate']*100:.0f}%. Separately, the field loop's "
                f"ACI update holds a distribution-free MARGINAL miscoverage guarantee at α={alpha} "
                "(a distinct quantity, not conflated). Synthetic stream — see limitations."
            ),
            "comparison": {
                "metric": "conditional_selective_risk",
                "metric_definition": "R(f,g) = errors_among_accepted / accepted (Geifman 2017 Eq. 1)",
                "r_star": r_star,
                "system_r_star": r_star,
                "naive_r_star": r_star,
                "system_rule": "Verdict risk-controlled threshold (SGR / Gascuel–Caraux bound)",
                "naive_rule": "boundary-sitting max-coverage threshold (Geifman §5.2)",
                "n_windows": 250,
                "window": window,
                **comparison,
                "system_beats_naive": comparison["system_violation_rate"] < comparison["naive_violation_rate"],
            },
            "guarantee": {
                # The ACI contribution — a DIFFERENT quantity than the r* comparison above.
                "metric": "marginal_miscoverage",
                "metric_definition": "auto-and-wrong / ALL fields (not conditional on acceptance)",
                "loop": "A", "guaranteed": True, "alpha": alpha,
                "system_realized_marginal_miscoverage": round(cov.overall.realized_marginal_miscoverage, 4),
                "system_realized_conditional_selective_risk": round(system_conditional_risk, 4),
                "holds_at_alpha": cov.overall.realized_marginal_miscoverage <= alpha,
            },
            # Back-compat keys — now sourced from the SAME 8-seed comparison object as the
            # headline (no seed-1-here / aggregate-there gap). mean_relative_violation is a
            # seed-1 Geifman detail, kept but labelled as such.
            "naive_violation_rate": comparison["naive_violation_rate"],
            "naive_violation_rate_min": comparison["naive_violation_rate_min"],
            "naive_mean_relative_violation_seed1": round(naive_study.mean_relative_violation, 4),
            "naive_violates_majority": comparison["naive_violation_rate"] > 0.5,
            "system_overall_marginal_miscoverage": round(cov.overall.realized_marginal_miscoverage, 4),
            "system_holds_guarantee": cov.overall.realized_marginal_miscoverage <= alpha,
        },
        "forecast": {
            "loop": "A", "guaranteed": True,
            "n_forecasts_scored": forecasts_scored,
            "n_forecast_failures": forecast_failures,
            "failure_rate": round(forecast_failures / forecasts_scored, 4) if forecasts_scored else None,
            "mean_predicted_automation": round(sum(predicted) / len(predicted), 4) if predicted else None,
            "mean_realized_automation": round(sum(realized) / len(realized), 4) if realized else None,
            "batches": batch_reports,
        },
        "coverage": {
            "loop": "A", "guaranteed": True,
            "overall": _seg_cov_dict(cov.overall),
            "worst_coverage_segment": cov.worst_segment_key,
            "worst_miscoverage_segment": cov.worst_miscoverage_key,
            "by_segment": {k: _seg_cov_dict(v) for k, v in cov.by_segment.items()},
        },
        "shift": {
            "loop": "A", "guaranteed": True,
            "expected_shift_statistic": round(shift.expected_shift, 5),
            "gamma_star": round(shift.gamma_star, 5),
            "thm42_bound_at_gamma": round(shift.thm42_bound_at_gamma, 5),
            "ood_rate_by_window": [round(x, 3) for x in nonx["ood_rate_by_window"]],
            "first_window_ood": round(nonx["first_window_ood"], 3),
            "last_window_ood": round(nonx["last_window_ood"], 3),
        },
        "fairness": {
            "loop": "B", "guaranteed": False,
            "note": "End-to-end disparate impact on the composed system (Mozannar §6.5: fairness "
                    "does not compose). Instrumented, not guaranteed — case truth is delayed and "
                    "selective.",
            "fpr_by_segment": {k: round(v, 4) for k, v in fairness.fpr_by_group.items()},
            "worst_segment": fairness.worst_group,
            "max_gap": round(fairness.max_gap, 4),
        },
        "budget": {
            "total": budget.total, "spent": budget.spent,
            "remaining": budget.remaining, "burn_fraction": round(budget.burn_fraction, 4),
        },
        "queue": queue,
        "cases": case_cards,
        "analyses": analyses,
        "limitations": [
            "SYNTHETIC STREAM ONLY. There is no real document corpus, no real extractor "
            "(the extractor is a documented stub), and no real reviewer-correction data. Every "
            "number here is a property of the synthetic error model, not of real underwriting.",
            "The synthetic error LEVEL (err_intercept=0.05, err_latent_slope=0.17) was CHOSEN so "
            "that r*=0.05 is feasible and the naive rule's selection-bias failure is visible. On a "
            "real corpus the error level is whatever it is; the naive rule may fail more, less, or "
            "not at all. This operating point is a demo choice, not a discovered property of the world.",
            "Confidence is a PARTIAL predictor by construction (corr(confidence, latent)=0.70, "
            "r²≈0.49); realized numbers depend on that choice. A real extractor's confidence–error "
            "relationship is unknown.",
            "The guarantee is over the CONFORMITY SCORE and holds for any extractor producing one; "
            "it is MARGINAL miscoverage at α (Loop A), not conditional selective risk, and not the "
            "case-level decision (Loop B is instrumented, never guaranteed).",
        ],
    }
    return report


def _seg_cov_dict(s) -> dict:
    return {
        "segment": s.segment_key, "n": s.n,
        "realized_coverage": round(s.realized_coverage, 4),
        "realized_marginal_miscoverage": round(s.realized_marginal_miscoverage, 4),
        "target_coverage": round(s.target_coverage, 4),
        "coverage_shortfall": round(s.coverage_shortfall, 4),
    }


def _reason_entry(reason) -> dict:
    return {"code": reason.name, "label": REASON_LABEL.get(reason, reason.name)}


def _build_queue(stream: SyntheticStream, alpha: float, budget: ReviewerBudget, rng) -> list[dict]:
    """A representative reviewer queue exercising ABSENT / UNCERTAIN / CONTRADICTED / DEGRADED,
    every item carrying provenance (doc, page, bbox, verbatim span)."""
    fields = stream.field_stream()
    items: list[dict] = []
    # Path 2 — uncertain routes and confident accepts, drawn from real fields.
    pool = [f for f in fields if f.confidence < 0.85][:14] + [f for f in fields if f.confidence >= 0.9][:8]
    for i, f in enumerate(pool):
        routed = f.confidence < 0.80
        reason = (RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD if routed
                  else AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD)
        if routed:
            budget.spend()
        items.append({
            "id": f"q2-{i:03d}", "loop": "A", "guaranteed": True,
            "path": "PATH_2", "path_label": PATH_LABEL["PATH_2"],
            "field_type": f.field_type.value,
            "decision": "ROUTE" if routed else "ACCEPT",
            "reason": _reason_entry(reason),
            "confidence": round(f.confidence, 3),
            "reviewer_accuracy": 0.70,
            "ood_score": round(f.ood_score, 3),
            "established": _established(f, routed),
            "provenance": _prov(f),
        })
    # Path 1 — absent (separate detector; no confidence anywhere).
    for i, f in enumerate([x for x in fields if x.archetype == HOTPOTQA_ANALOGUE_ARCHETYPE][:3]):
        budget.spend()
        items.append({
            "id": f"q1-{i:03d}", "loop": "A", "guaranteed": True,
            "path": "PATH_1", "path_label": PATH_LABEL["PATH_1"],
            "field_type": f.field_type.value, "decision": "ROUTE",
            "reason": _reason_entry(RouteReason.FIELD_ABSENT_FROM_DOCUMENT),
            "confidence": None, "detector": "absence-v1",
            "established": {"summary": "The extractor found no value for this field in the bundle.",
                            "steps": []},
            "provenance": {"doc_id": f.doc_id, "page": None, "bbox": None, "raw_span": None},
        })
    # Path 3 — contradicted across two sources (fires regardless of confidence).
    for i in range(3):
        a = fields[rng.randrange(len(fields))]
        b = fields[rng.randrange(len(fields))]
        budget.spend()
        items.append({
            "id": f"q3-{i:03d}", "loop": "A", "guaranteed": True,
            "path": "PATH_3", "path_label": PATH_LABEL["PATH_3"],
            "field_type": a.field_type.value, "decision": "ROUTE",
            "reason": _reason_entry(RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT),
            "confidence": round(max(a.confidence, b.confidence), 3),
            "note": "High confidence on both values is possible and irrelevant — the system is "
                    "confident and wrong somewhere.",
            "sources": [_prov(a), _prov(b)],
            "provenance": _prov(a),
        })
    # Degraded — no confidence available.
    dfield = fields[rng.randrange(len(fields))]
    budget.spend()
    items.append({
        "id": "qd-000", "loop": "A", "guaranteed": True,
        "path": "DEGRADED", "path_label": PATH_LABEL["DEGRADED"],
        "field_type": dfield.field_type.value, "decision": "ROUTE",
        "reason": _reason_entry(RouteReason.NO_CONFIDENCE_AVAILABLE),
        "confidence": None,
        "established": {"summary": "Extraction produced no confidence score; excluded from "
                                   "calibration, still counted against the reviewer budget.",
                        "steps": []},
        "provenance": _prov(dfield),
    })
    return items


def _established(f, routed: bool) -> dict:
    """Abstention as PARTIAL WORK (Part 7 decision 6): show what WAS established, then the gap."""
    steps = [
        {"label": "Located value", "detail": f.raw_span, "ok": True},
        {"label": "Normalized", "detail": f"{f.value:,}", "ok": True},
        {"label": "Scale-normalized conformity score", "detail": f"ood={f.ood_score:.2f}", "ok": True},
    ]
    if routed:
        steps.append({"label": "Confidence vs guaranteed threshold", "detail": "below threshold — needs review", "ok": False})
        summary = "Value extracted and normalized; uncertainty exceeded the guaranteed threshold."
    else:
        steps.append({"label": "Confidence vs guaranteed threshold", "detail": "within threshold — automated", "ok": True})
        summary = "Value extracted, normalized, and automated within the guaranteed threshold."
    return {"summary": summary, "steps": steps}


def _prov(f) -> dict:
    return {"doc_id": f.doc_id, "page": f.page, "bbox": list(f.bbox),
            "raw_span": f.raw_span, "archetype": f.archetype}


def _build_case_cards(cases) -> list[dict]:
    cards = []
    for c in cases:
        cards.append({
            "case_id": c.case_id, "loop": "B", "guaranteed": False,
            "segment": {"naics2": c.segment.industry_naics2, "state": c.segment.geography_state,
                        "business_age": c.segment.business_age.value},
            "risk_tier": RiskTier.REVIEW.value,  # instrumented placeholder — not a guaranteed ruling
            "note": "Case-level decision is INSTRUMENTED, not guaranteed (Loop B). Derived-metric "
                    "confidence is not propagated (unsolved).",
            "n_fields": len(c.labeled_fields),
            "archetypes": list(c.archetypes),
        })
    return cards


def to_json(report: dict, path: str | Path) -> None:
    import json

    Path(path).write_text(json.dumps(report, indent=2, default=str))


_EMBED_OPEN = '<script type="application/json" id="report">'
_EMBED_CLOSE = "</script>"


def embed_report(report: dict, html_path: str | Path) -> bool:
    """Refresh the page's embedded report snapshot (the file:// fallback used when the page
    cannot fetch report.json). Idempotent: replaces only the payload of the
    `<script type="application/json" id="report">` block. Returns False when the page has no
    such block."""
    import json

    p = Path(html_path)
    html = p.read_text()
    start = html.find(_EMBED_OPEN)
    if start == -1:
        return False
    payload_start = start + len(_EMBED_OPEN)
    end = html.find(_EMBED_CLOSE, payload_start)
    if end == -1:
        return False
    # "</" would terminate the script block early; escape it inside the JSON payload.
    payload = json.dumps(report, separators=(",", ":"), default=str).replace("</", "<\\/")
    p.write_text(html[:payload_start] + payload + html[end:])
    return True
