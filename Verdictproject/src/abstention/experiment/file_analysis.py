"""Per-file analysis records — the workspace's terminal timeline and memory graph.

A "file" is a credit file: the document bundle behind one application (StreamCase). The
experiment selects a small, deterministic set of showcase bundles from the real stream and
replays each through the same decision rule the field loop applied (the batch's frozen τ_t
and the reviewer-accuracy gate), producing:

- an ordered, user-facing event log (what the terminal renders — recorded, then replayed),
- findings derived by the shared memory.builder rules (terminal and graph cannot disagree),
- a validated MemoryGraph, published only when the analysis reaches COMPLETED or PARTIAL.

Honesty rules: every event states something the pipeline actually did or knows from the
record; a FAILED analysis publishes no graph; derived metrics are BLOCKED, never given a
fabricated propagated confidence. Absent/contradicted/degraded showcases follow the same
representative-injection convention as report._build_queue, seeded and deterministic.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

from ..data.synthetic import HOTPOTQA_ANALOGUE_ARCHETYPE, LabeledField, StreamCase
from ..domain.taxonomy import AcceptReason, RouteReason
from ..memory import (
    AnalysisStatus,
    FieldOutcome,
    Finding,
    METRIC_INPUTS,
    SourceRef,
    assert_valid,
    build_file_graph,
    derive_findings,
)

REVIEWER_ACCURACY = 0.70  # matches ReviewerAccuracyModel default used by build_report

# Fixed stage progression shown by the terminal's progress indicator.
STAGES = ("QUEUE", "LOAD", "EXTRACT", "SCORE", "DECIDE", "RECONCILE", "DERIVE", "GRAPH", "DONE")


@dataclass(frozen=True, slots=True)
class _BatchContext:
    batch_id: str
    tau: float
    alpha_t: float


def _src(f: LabeledField) -> SourceRef:
    return SourceRef(doc_id=f.doc_id, archetype=f.archetype, page=f.page,
                     bbox=f.bbox, raw_span=f.raw_span)


def _decide(f: LabeledField, tau: float) -> tuple[str, RouteReason | AcceptReason]:
    """The field loop's acceptance rule with the batch's frozen τ (field_loop.process_batch)."""
    s = 1.0 - f.confidence
    if s > tau:
        return "ROUTE", RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD
    if f.confidence < REVIEWER_ACCURACY:
        return "ROUTE", RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY
    return "ACCEPT", AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD


def _outcomes_for_case(case: StreamCase, ctx: _BatchContext, *, absent_at: int | None = None,
                       degraded_at: int | None = None, conflict_at: int | None = None,
                       ) -> list[FieldOutcome]:
    outcomes: list[FieldOutcome] = []
    fields = case.labeled_fields
    for i, f in enumerate(fields):
        if i == absent_at:
            outcomes.append(FieldOutcome(
                index=i, field_type=f.field_type, path="PATH_1", decision="ROUTE",
                reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT,
                source=SourceRef(doc_id=f.doc_id, archetype=f.archetype),
                tau=ctx.tau,
            ))
            continue
        if i == degraded_at:
            outcomes.append(FieldOutcome(
                index=i, field_type=f.field_type, path="DEGRADED", decision="ROUTE",
                reason=RouteReason.NO_CONFIDENCE_AVAILABLE, source=_src(f),
                ood_score=round(f.ood_score, 3), tau=ctx.tau,
            ))
            continue
        if i == conflict_at:
            other = fields[(i + 1) % len(fields)]
            outcomes.append(FieldOutcome(
                index=i, field_type=f.field_type, path="PATH_3", decision="ROUTE",
                reason=RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT, source=_src(f),
                confidence=round(f.confidence, 3), reviewer_accuracy=REVIEWER_ACCURACY,
                ood_score=round(f.ood_score, 3), tau=ctx.tau, conflict_source=_src(other),
            ))
            continue
        decision, reason = _decide(f, ctx.tau)
        outcomes.append(FieldOutcome(
            index=i, field_type=f.field_type, path="PATH_2", decision=decision, reason=reason,
            source=_src(f), confidence=round(f.confidence, 3),
            reviewer_accuracy=REVIEWER_ACCURACY, ood_score=round(f.ood_score, 3), tau=ctx.tau,
        ))
    return outcomes


# ---- event log -----------------------------------------------------------------------


class _EventLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add(self, stage: str, kind: str, text: str, **refs: Any) -> None:
        ev: dict[str, Any] = {"seq": len(self.events), "stage": stage, "kind": kind, "text": text}
        ev.update({k: v for k, v in refs.items() if v is not None})
        self.events.append(ev)


def _extract_events(log: _EventLog, outcomes: Sequence[FieldOutcome]) -> None:
    for o in outcomes:
        s = o.source
        if o.path == "PATH_1":
            log.add("EXTRACT", "warning",
                    f"No value found for {o.field_type.value} in {s.doc_id} — absence-v1 fired "
                    "(a detector outcome, not low confidence)",
                    field=o.field_type.value, doc_id=s.doc_id)
        elif o.path == "DEGRADED":
            log.add("EXTRACT", "warning",
                    f"Located {o.field_type.value} on {s.doc_id} p.{s.page} — extractor "
                    "returned no confidence score",
                    field=o.field_type.value, doc_id=s.doc_id)
        else:
            log.add("EXTRACT", "agent",
                    f"Located {o.field_type.value} on {s.doc_id} p.{s.page} — span “{s.raw_span}”",
                    field=o.field_type.value, doc_id=s.doc_id)


def _decide_events(log: _EventLog, outcomes: Sequence[FieldOutcome],
                   findings: Sequence[Finding]) -> None:
    finding_by_index = {f.outcome.index: f for f in findings}
    for o in outcomes:
        if o.path == "PATH_3":
            continue  # contradictions are announced in the RECONCILE stage
        f = finding_by_index.get(o.index)
        if o.decision == "ACCEPT":
            s = 1.0 - (o.confidence or 0.0)
            log.add("DECIDE", "success",
                    f"ACCEPT {o.field_type.value} — s = {s:.3f} ≤ τ = {o.tau:.3f}, "
                    f"confidence {o.confidence:.3f} ≥ reviewer {o.reviewer_accuracy:.2f}",
                    field=o.field_type.value)
            continue
        assert f is not None
        if o.path == "PATH_1":
            detail = "field absent — absence-v1 detector, not a confidence outcome"
        elif o.path == "DEGRADED":
            detail = "no confidence score; excluded from calibration, budget still burned"
        elif o.reason is RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY:
            detail = (f"confidence {o.confidence:.3f} < reviewer accuracy "
                      f"{o.reviewer_accuracy:.2f}")
        else:
            detail = f"s = {1.0 - (o.confidence or 0.0):.3f} > τ = {o.tau:.3f}"
        log.add("DECIDE", "finding",
                f"ROUTE {o.field_type.value} — {detail} ({o.reason.value})",
                field=o.field_type.value, finding_id=f.id, severity=f.severity.value)


def _reconcile_events(log: _EventLog, outcomes: Sequence[FieldOutcome],
                      findings: Sequence[Finding]) -> None:
    conflicts = [f for f in findings if f.outcome.path == "PATH_3"]
    if not conflicts:
        log.add("RECONCILE", "info", "Cross-document reconciliation — no conflicts")
        return
    for f in conflicts:
        o = f.outcome
        a, b = o.source, o.conflict_source
        log.add("RECONCILE", "finding",
                f"CONFLICT {o.field_type.value} — {a.doc_id} p.{a.page} “{a.raw_span}” vs "
                f"{b.doc_id} p.{b.page} “{b.raw_span}”; routes at any confidence "
                f"(here {o.confidence:.2f})",
                field=o.field_type.value, finding_id=f.id, severity=f.severity.value)


def _derive_events(log: _EventLog, outcomes: Sequence[FieldOutcome],
                   findings: Sequence[Finding]) -> None:
    present = {o.field_type for o in outcomes}
    finding_fields = {f.outcome.field_type for f in findings}
    for metric, inputs in METRIC_INPUTS.items():
        involved = [ft for ft in inputs if ft in present]
        if not involved:
            continue
        blockers = sorted(ft.value for ft in set(inputs) & finding_fields)
        missing = sorted(ft.value for ft in inputs if ft not in present)
        if blockers or missing:
            why = " and ".join(x for x in (
                f"unresolved input {', '.join(blockers)}" if blockers else "",
                f"missing input {', '.join(missing)}" if missing else "") if x)
            log.add("DERIVE", "warning", f"{metric} blocked — {why}; Verdict does not compute "
                    "on unreviewed inputs")
        else:
            log.add("DERIVE", "info",
                    f"{metric} inputs resolved — computable downstream (Loop B, instrumented; "
                    "no propagated confidence exists)")


# ---- analysis assembly ---------------------------------------------------------------


def _build_analysis(case: StreamCase, ctx: _BatchContext, generated_at: str, *,
                    absent_at: int | None = None, degraded_at: int | None = None,
                    conflict_at: int | None = None, fail_at: int | None = None,
                    ) -> dict[str, Any]:
    analysis_id = f"an-{case.case_id}"
    file_label = f"{case.case_id}.bundle"
    fields = case.labeled_fields
    docs: dict[str, str] = {}
    for f in fields:
        docs.setdefault(f.doc_id, f.archetype)

    log = _EventLog()
    log.add("QUEUE", "system", f"Analysis {analysis_id} queued — {file_label}: "
            f"{len(docs)} documents, {len(fields)} target fields")
    log.add("LOAD", "system", f"Opened bundle {file_label}")
    for doc_id, archetype in docs.items():
        log.add("LOAD", "file", f"Loaded {doc_id} ({archetype})", doc_id=doc_id)

    # ---- failure path: extraction aborts the bundle; no graph is published -----------
    if fail_at is not None:
        failed_doc = fields[fail_at].doc_id
        partial = _outcomes_for_case(case, ctx)[:fail_at]
        _extract_events(log, partial)
        log.add("EXTRACT", "error",
                f"EXTRACTION_ERROR — {failed_doc} could not be parsed; bundle aborted after "
                f"{fail_at} of {len(fields)} fields", doc_id=failed_doc)
        log.add("DONE", "error",
                "Analysis FAILED — no decisions issued and no memory graph published; "
                "resolve the document fault and re-run")
        return {
            "analysis_id": analysis_id, "case_id": case.case_id, "file_label": file_label,
            "loop": "A", "guaranteed": True, "status": AnalysisStatus.FAILED.value,
            "segment": _segment_dict(case), "archetypes": sorted(docs.values()),
            "documents": [{"doc_id": d, "archetype": a} for d, a in docs.items()],
            "n_fields": len(fields), "n_automated": 0, "n_routed": 0,
            "worst_severity": "CRITICAL", "batch_id": ctx.batch_id,
            "tau": round(ctx.tau, 4), "alpha_t": round(ctx.alpha_t, 4),
            "error": {"reason": RouteReason.EXTRACTION_ERROR.value, "doc_id": failed_doc},
            "events": log.events, "findings": [], "graph": None,
        }

    outcomes = _outcomes_for_case(case, ctx, absent_at=absent_at, degraded_at=degraded_at,
                                  conflict_at=conflict_at)
    findings = derive_findings(outcomes)
    _extract_events(log, outcomes)

    log.add("SCORE", "agent",
            f"Scored scale-normalized conformity for {len(outcomes)} fields — "
            f"τ_t = {ctx.tau:.3f} (α_t = {ctx.alpha_t:.3f}) from the calibration window")
    _decide_events(log, outcomes, findings)
    _reconcile_events(log, outcomes, findings)
    _derive_events(log, outcomes, findings)

    n_accepted = sum(1 for o in outcomes if o.decision == "ACCEPT")
    n_routed = len(outcomes) - n_accepted
    has_gap = any(o.path in ("PATH_1", "DEGRADED") for o in outcomes)
    status = AnalysisStatus.PARTIAL if has_gap else AnalysisStatus.COMPLETED

    graph = assert_valid(build_file_graph(
        analysis_id=analysis_id, file_label=file_label, outcomes=outcomes, status=status,
        generated_at=generated_at,
        context={"segment": _segment_dict(case), "archetypes": sorted(docs.values()),
                 "batch_id": ctx.batch_id},
    ))
    md = graph.metadata
    log.add("GRAPH", "system",
            f"Memory graph assembled — {md.counts['nodes']} nodes, {md.counts['edges']} edges; "
            "validation passed")
    if status is AnalysisStatus.PARTIAL:
        log.add("DONE", "warning",
                f"Analysis PARTIAL — {n_accepted}/{len(outcomes)} automated, {n_routed} routed; "
                "absent or degraded fields flagged for sourcing")
    else:
        log.add("DONE", "success",
                f"Analysis complete — {n_accepted}/{len(outcomes)} automated, {n_routed} "
                f"routed · worst severity {md.worst_severity.value}")

    return {
        "analysis_id": analysis_id, "case_id": case.case_id, "file_label": file_label,
        "loop": "A", "guaranteed": True, "status": status.value,
        "segment": _segment_dict(case), "archetypes": sorted(set(docs.values())),
        "documents": [{"doc_id": d, "archetype": a} for d, a in docs.items()],
        "n_fields": len(outcomes), "n_automated": n_accepted, "n_routed": n_routed,
        "worst_severity": md.worst_severity.value, "batch_id": ctx.batch_id,
        "tau": round(ctx.tau, 4), "alpha_t": round(ctx.alpha_t, 4),
        "error": None, "events": log.events,
        "findings": [{
            "id": f.id, "severity": f.severity.value, "field_type": f.outcome.field_type.value,
            "title": f.title, "reason": f.outcome.reason.value, "remediation": f.remediation,
        } for f in findings],
        "graph": graph.to_dict(),
    }


def _segment_dict(case: StreamCase) -> dict[str, str]:
    return {"naics2": case.segment.industry_naics2, "state": case.segment.geography_state,
            "business_age": case.segment.business_age.value}


# ---- showcase selection --------------------------------------------------------------


def build_file_analyses(cases: Sequence[StreamCase], batch_contexts: Sequence[_BatchContext],
                        cases_per_batch: int, generated_at: str, seed: int) -> list[dict[str, Any]]:
    """Select a deterministic set of showcase bundles covering every terminal state and path,
    then build each one's record. Scan starts after calibration warm-up so decisions use a
    real, non-zero τ_t."""
    rng = random.Random(seed + 11)

    def ctx_for(idx: int) -> _BatchContext | None:
        bi = idx // cases_per_batch
        if bi >= len(batch_contexts):
            return None
        return batch_contexts[bi]

    def would_accept(f: LabeledField, tau: float) -> bool:
        return (1.0 - f.confidence) <= tau and f.confidence >= REVIEWER_ACCURACY

    picks: dict[str, tuple[StreamCase, _BatchContext]] = {}
    dscr_fields = set(METRIC_INPUTS["DSCR"])
    for idx, case in enumerate(cases):
        if len(picks) == 6:
            break
        ctx = ctx_for(idx)
        if ctx is None or ctx.tau <= 0.0 or idx < 4 * cases_per_batch:
            continue
        if any(case is c for c, _ in picks.values()):
            continue
        fields = case.labeled_fields
        docs = {f.doc_id for f in fields}
        accepts = sum(1 for f in fields if would_accept(f, ctx.tau))
        routes = len(fields) - accepts
        types = {f.field_type for f in fields}
        has_multi = any(f.archetype == HOTPOTQA_ANALOGUE_ARCHETYPE for f in fields)
        if "uncertain" not in picks and 2 <= routes <= 4 and len(docs) >= 2 and not has_multi:
            picks["uncertain"] = (case, ctx)
        elif "contradicted" not in picks and len(docs) >= 3 and accepts >= 3:
            picks["contradicted"] = (case, ctx)
        elif "absent" not in picks and has_multi and routes <= 3:
            picks["absent"] = (case, ctx)
        elif "clean" not in picks and routes == 0 and dscr_fields <= types:
            picks["clean"] = (case, ctx)
        elif "degraded" not in picks and routes <= 2 and len(docs) >= 2:
            picks["degraded"] = (case, ctx)
        elif "failed" not in picks and len(docs) >= 2:
            picks["failed"] = (case, ctx)
    # Fallback for the strict clean profile: relax the metric-coverage requirement.
    if "clean" not in picks:
        for idx, case in enumerate(cases):
            ctx = ctx_for(idx)
            if ctx is None or ctx.tau <= 0.0 or any(case is c for c, _ in picks.values()):
                continue
            if all(would_accept(f, ctx.tau) for f in case.labeled_fields):
                picks["clean"] = (case, ctx)
                break

    analyses: list[dict[str, Any]] = []
    order = ("uncertain", "contradicted", "absent", "degraded", "clean", "failed")
    for profile in order:
        if profile not in picks:
            continue
        case, ctx = picks[profile]
        fields = case.labeled_fields
        if profile == "contradicted":
            conflict_at = max(range(len(fields)), key=lambda i: fields[i].confidence)
            analyses.append(_build_analysis(case, ctx, generated_at, conflict_at=conflict_at))
        elif profile == "absent":
            absent_at = next(i for i, f in enumerate(fields)
                             if f.archetype == HOTPOTQA_ANALOGUE_ARCHETYPE)
            analyses.append(_build_analysis(case, ctx, generated_at, absent_at=absent_at))
        elif profile == "degraded":
            analyses.append(_build_analysis(case, ctx, generated_at,
                                            degraded_at=rng.randrange(len(fields))))
        elif profile == "failed":
            analyses.append(_build_analysis(case, ctx, generated_at,
                                            fail_at=2 if len(fields) > 2 else 1))
        else:
            analyses.append(_build_analysis(case, ctx, generated_at))
    return analyses
