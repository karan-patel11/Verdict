"""Memory-graph builder — pure transformation from analyzed-field outcomes to a MemoryGraph.

The builder is the single source of truth for what counts as a finding, how severe it is,
and which downstream metric it blocks. The terminal event log and the graph both consume
`derive_findings`, so the two surfaces can never disagree about what was found.

Severity is a fixed function of the path taxonomy, not a tunable aesthetic:

- PATH_3 CONTRADICTED  → HIGH      (the system is confident and wrong somewhere)
- EXTRACTION_ERROR     → CRITICAL  (the pipeline itself faulted)
- PATH_1 ABSENT        → MEDIUM    (human sourcing required; a detector outcome, not doubt)
- DEGRADED             → MEDIUM    (no confidence score; excluded from calibration)
- PATH_2 routed        → LOW       (calibrated abstention doing its job)

Accepted fields produce no finding. Derived metrics NEVER carry a propagated confidence
(derived/propagation.py is deliberately unsolved); a metric fed by a routed field is BLOCKED.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ..domain.taxonomy import AcceptReason, RouteReason
from ..domain.types import FieldType
from .schema import (
    AnalysisStatus,
    EdgeRelation,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    MemoryGraph,
    NodeCategory,
    NodeStatus,
    Severity,
    SourceRef,
    worst_severity,
)

# Derived metrics and the exact fields they are deterministic functions of (derived/metrics.py).
METRIC_INPUTS: Mapping[str, tuple[FieldType, ...]] = {
    "DSCR": (FieldType.NET_INCOME, FieldType.DEPRECIATION, FieldType.TOTAL_DEBT_SERVICE),
    "ADB_RATIO": (FieldType.AVG_DAILY_BALANCE, FieldType.TOTAL_DEBT_SERVICE),
}

_METRIC_DESCRIPTION = {
    "DSCR": "Debt Service Coverage Ratio = (net income + depreciation) / total debt service. "
            "Computed in Loop B — instrumented, not guaranteed; no propagated confidence exists "
            "(hierarchical propagation is unsolved and deliberately not faked).",
    "ADB_RATIO": "Average daily balance / monthly debt service. Computed in Loop B — "
                 "instrumented, not guaranteed; no propagated confidence exists.",
}

_PATH_CHECK = {
    "PATH_2": ("check:calibrated-gate", "Conformal acceptance rule (τ gate)",
               "Accept iff nonconformity s = 1 − confidence ≤ τ_t AND raw extractor confidence ≥ "
               "reviewer accuracy. τ_t is the conformally-calibrated threshold (ACI); the "
               "confidence VALUE is the extractor's raw softmax (the RF calibrator is off-path — "
               "see meta.calibrator). Before calibration warms up, everything routes."),
    "PATH_1": ("check:absence", "Absence detector",
               "A separate detector (absence-v1) that reports a field as not present in the "
               "bundle. Never a low-confidence outcome — absence and uncertainty are distinct "
               "paths by construction."),
    "PATH_3": ("check:reconciliation", "Cross-document reconciliation",
               "Compares the same field across documents. A conflict routes at any confidence "
               "and is never suppressed by budget."),
    "DEGRADED": ("check:confidence-availability", "Confidence availability",
                 "Extraction must produce a confidence score. A missing score degrades the item: "
                 "routed, excluded from calibration, still counted against reviewer budget."),
}

_PATH2_REVIEW_REMEDIATION = (
    "Review the extracted value against the verbatim span; confirm or correct it. "
    "The correction feeds the calibrator's ACI update."
)

_FINDING_TEXT = {
    "PATH_2": ("Uncertainty above the guaranteed threshold", _PATH2_REVIEW_REMEDIATION),
    "PATH_1": ("Field not present in the document bundle",
               "Locate the field in the bundle or confirm it is genuinely absent. Absence is a "
               "detector outcome, not low confidence — do not guess a value."),
    "PATH_3": ("Sources disagree on this value",
               "Reconcile the two sources and record which value is defensible. High confidence "
               "on both is possible and irrelevant — the system is confident and wrong "
               "somewhere."),
    "DEGRADED": ("No confidence score available",
                 "Verify the extracted value manually and inspect extractor health for this "
                 "archetype; the item was excluded from calibration."),
    "ERROR": ("Extraction failed for this field",
              "Resolve the document fault and re-run extraction for this bundle."),
}

_PATH_SEVERITY = {
    "PATH_2": Severity.LOW,
    "PATH_1": Severity.MEDIUM,
    "DEGRADED": Severity.MEDIUM,
    "PATH_3": Severity.HIGH,
    "ERROR": Severity.CRITICAL,
}


@dataclass(frozen=True, slots=True)
class FieldOutcome:
    """One analyzed field with its decision — the builder's input contract, produced by the
    experiment's file-analysis assembly from real stream fields and real loop state."""

    index: int
    field_type: FieldType
    path: str  # PATH_1 / PATH_2 / PATH_3 / DEGRADED / ERROR
    decision: str  # ACCEPT / ROUTE
    reason: RouteReason | AcceptReason
    source: SourceRef
    confidence: float | None = None
    reviewer_accuracy: float | None = None
    ood_score: float | None = None
    tau: float | None = None  # the frozen threshold the decision was made against
    conflict_source: SourceRef | None = None  # PATH_3: the second, disagreeing source

    @property
    def is_finding(self) -> bool:
        return self.decision == "ROUTE"


@dataclass(frozen=True, slots=True)
class Finding:
    """Typed intermediate shared by the graph builder and the terminal event log."""

    id: str
    outcome: FieldOutcome
    severity: Severity
    title: str
    remediation: str
    check_id: str

    @property
    def field_node_id(self) -> str:
        return _field_node_id(self.outcome)


class OutcomeInvariantError(ValueError):
    """A FieldOutcome violates the path/decision invariants (e.g. an accepted contradiction)."""


def _assert_outcomes_valid(outcomes: Sequence[FieldOutcome]) -> None:
    """Only PATH_2 fields may be ACCEPTed. A CONTRADICTED (PATH_3), ABSENT (PATH_1), DEGRADED,
    or ERROR field marked ACCEPT is a silent invariant hole — reject it (audit F6)."""
    for o in outcomes:
        if o.decision not in ("ACCEPT", "ROUTE"):
            raise OutcomeInvariantError(
                f"decision must be ACCEPT or ROUTE, got {o.decision!r} for {o.field_type.value}"
            )
        if o.decision == "ACCEPT" and o.path != "PATH_2":
            raise OutcomeInvariantError(
                f"only PATH_2 fields may be ACCEPTed; {o.path} field {o.field_type.value!r} was "
                "marked ACCEPT — a CONTRADICTED/ABSENT/DEGRADED/ERROR field is never accepted, at "
                "any confidence (path invariant; audit F6)"
            )


def _field_node_id(o: FieldOutcome) -> str:
    return f"field:{o.index}:{o.field_type.value}"


def _doc_node_id(doc_id: str) -> str:
    return f"doc:{doc_id}"


def derive_findings(outcomes: Sequence[FieldOutcome]) -> tuple[Finding, ...]:
    """Every routed field yields exactly one finding; accepted fields yield none."""
    findings: list[Finding] = []
    for o in outcomes:
        if not o.is_finding:
            continue
        title, remediation = _FINDING_TEXT[o.path]
        # The acceptance rule has two clauses; name the one that actually fired.
        if o.reason is RouteReason.CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY:
            title = "Confidence below the reviewer-accuracy gate"
        check_id, _, _ = _PATH_CHECK.get(o.path, _PATH_CHECK["PATH_2"])
        if o.path == "ERROR":
            check_id = "check:extraction"
        findings.append(
            Finding(
                id=f"finding:{o.index}:{o.field_type.value}",
                outcome=o,
                severity=_PATH_SEVERITY[o.path],
                title=title,
                remediation=remediation,
                check_id=check_id,
            )
        )
    return tuple(findings)


def _fmt_conf(o: FieldOutcome) -> str:
    if o.confidence is None:
        return "no confidence score"
    ra = f" vs reviewer {o.reviewer_accuracy:.2f}" if o.reviewer_accuracy is not None else ""
    return f"raw softmax {o.confidence:.3f}{ra}"


def build_file_graph(
    *,
    analysis_id: str,
    file_label: str,
    outcomes: Sequence[FieldOutcome],
    status: AnalysisStatus,
    generated_at: str,
    context: Mapping[str, object] | None = None,
) -> MemoryGraph:
    """Assemble the standardized graph for one analyzed file.

    Shape is invariant: FILE → SUMMARY/DOCUMENTs → FIELDs → CHECKs → FINDINGs →
    EVIDENCE / METRICs / ACTIONs. Only payloads, counts, and issue states vary by file.

    Refuses malformed outcomes rather than trusting the caller (audit F6): a CONTRADICTED,
    ABSENT, DEGRADED, or ERROR field marked ACCEPT is a path-invariant violation (mirrors the
    domain FieldDecision rule that Path 1/Path 3 can never be accepted, at any confidence) —
    it must RAISE, never silently produce no finding.
    """
    _assert_outcomes_valid(outcomes)
    findings = derive_findings(outcomes)
    finding_by_field: dict[str, Finding] = {f.field_node_id: f for f in findings}
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    def add_edge(source: str, target: str, rel: EdgeRelation, *, propagates: bool = False,
                 weight: float | None = None) -> None:
        edges.append(GraphEdge(id=f"{source}~{rel.value}~{target}", source=source, target=target,
                               relation=rel, propagates_issue=propagates, weight=weight))

    ctx = dict(context or {})
    n_accepted = sum(1 for o in outcomes if o.decision == "ACCEPT")
    n_routed = len(outcomes) - n_accepted
    overall = worst_severity([f.severity for f in findings])

    # ---- file root -------------------------------------------------------------------
    file_id = "file"
    file_status = NodeStatus.NEEDS_REVIEW if findings else NodeStatus.VALIDATED
    if status is AnalysisStatus.FAILED:
        file_status = NodeStatus.FAILED
    nodes.append(GraphNode(
        id=file_id, analysis_id=analysis_id, category=NodeCategory.FILE,
        label=file_label,
        summary=f"{len(outcomes)} fields · {n_accepted} automated · {n_routed} routed",
        description="The analyzed credit file — a document bundle for one application. "
                    "Field-level decisions are Loop A (guaranteed); anything derived at case "
                    "level is Loop B (instrumented).",
        status=file_status, severity=overall,
        metadata={k: v for k, v in ctx.items() if k in ("segment", "archetypes", "batch_id")},
    ))

    # ---- summary ---------------------------------------------------------------------
    auto_rate = n_accepted / len(outcomes) if outcomes else 0.0
    tau_vals = [o.tau for o in outcomes if o.tau is not None]
    tau_txt = f"τ_t = {tau_vals[0]:.3f}" if tau_vals else "τ_t unavailable"
    nodes.append(GraphNode(
        id="summary", analysis_id=analysis_id, category=NodeCategory.SUMMARY,
        label="Analysis summary",
        summary=f"{auto_rate:.0%} automated · worst severity {overall.value}",
        description=f"{n_accepted} of {len(outcomes)} fields automated under the guaranteed "
                    f"threshold ({tau_txt}); {n_routed} routed to review. "
                    "Automation is per-field with a marginal miscoverage target — a routed "
                    "field is covered by the human, not a failure.",
        status=NodeStatus.INFO, severity=overall, parent_id=file_id,
    ))
    add_edge(file_id, "summary", EdgeRelation.SUMMARIZED_BY)

    # ---- documents (structural areas), in first-appearance order ---------------------
    doc_order: list[str] = []
    doc_refs: dict[str, SourceRef] = {}
    doc_fields: dict[str, list[FieldOutcome]] = {}
    for o in outcomes:
        refs = [o.source] + ([o.conflict_source] if o.conflict_source else [])
        for ref in refs:
            if ref.doc_id not in doc_refs:
                doc_refs[ref.doc_id] = ref
                doc_order.append(ref.doc_id)
        doc_fields.setdefault(o.source.doc_id, []).append(o)

    for doc_id in doc_order:
        ref = doc_refs[doc_id]
        members = doc_fields.get(doc_id, [])
        doc_sev = worst_severity([
            finding_by_field[fid].severity
            for fid in (_field_node_id(m) for m in members) if fid in finding_by_field
        ])
        nid = _doc_node_id(doc_id)
        nodes.append(GraphNode(
            id=nid, analysis_id=analysis_id, category=NodeCategory.DOCUMENT,
            label=doc_id, summary=f"{ref.archetype} · {len(members)} fields",
            description=f"Source document ({ref.archetype}). Every extracted value below "
                        "carries a verbatim span, page, and bounding box back into this "
                        "document.",
            status=NodeStatus.INFO, severity=doc_sev, parent_id=file_id,
            source=SourceRef(doc_id=doc_id, archetype=ref.archetype),
        ))
        add_edge(file_id, nid, EdgeRelation.CONTAINS)

    # ---- fields ----------------------------------------------------------------------
    for o in outcomes:
        fid = _field_node_id(o)
        finding = finding_by_field.get(fid)
        if o.decision == "ACCEPT":
            f_status, f_summary = NodeStatus.VALIDATED, "automated within the guaranteed threshold"
        elif o.path == "ERROR":
            f_status, f_summary = NodeStatus.FAILED, "extraction failed"
        else:
            f_status, f_summary = NodeStatus.NEEDS_REVIEW, "routed to review"
        span = o.source.raw_span
        nodes.append(GraphNode(
            id=fid, analysis_id=analysis_id, category=NodeCategory.FIELD,
            label=o.field_type.value,
            summary=(f"“{span}” · {f_summary}" if span else f_summary),
            description=f"Extracted field ({_fmt_conf(o)}"
                        + (f", ood {o.ood_score:.2f}" if o.ood_score is not None else "")
                        + f"). Decision: {o.decision} — {o.reason.value}.",
            status=f_status,
            severity=finding.severity if finding else Severity.NONE,
            confidence=o.confidence, reviewer_accuracy=o.reviewer_accuracy,
            source=o.source, parent_id=_doc_node_id(o.source.doc_id),
            finding_ids=(finding.id,) if finding else (),
            metadata={"decision": o.decision, "reason": o.reason.value, "path": o.path},
        ))
        add_edge(_doc_node_id(o.source.doc_id), fid, EdgeRelation.EXTRACTED)

    # ---- checks actually exercised ---------------------------------------------------
    seen_checks: dict[str, tuple[str, str]] = {}
    for o in outcomes:
        key = "PATH_2" if (o.path == "PATH_2" or o.path == "ERROR") else o.path
        if o.path == "ERROR":
            seen_checks.setdefault("check:extraction", (
                "Extraction", "Document parsing and field extraction for this bundle."))
            add_edge(_field_node_id(o), "check:extraction", EdgeRelation.CHECKED_BY)
            continue
        check_id, label, desc = _PATH_CHECK[key]
        seen_checks.setdefault(check_id, (label, desc))
        add_edge(_field_node_id(o), check_id, EdgeRelation.CHECKED_BY)
    for check_id, (label, desc) in seen_checks.items():
        tau_note = f" Current τ_t = {tau_vals[0]:.3f}." if (tau_vals and check_id == "check:calibrated-gate") else ""
        nodes.append(GraphNode(
            id=check_id, analysis_id=analysis_id, category=NodeCategory.CHECK,
            label=label, summary="rule exercised on this file",
            description=desc + tau_note, status=NodeStatus.INFO, parent_id="file",
        ))

    # ---- findings + evidence ---------------------------------------------------------
    for f in findings:
        o = f.outcome
        nodes.append(GraphNode(
            id=f.id, analysis_id=analysis_id, category=NodeCategory.FINDING,
            label=f.title,
            summary=f"{o.field_type.value} · {f.severity.value}",
            description=f"{f.title}. {_fmt_conf(o).capitalize()}. Reason code {o.reason.value} "
                        f"(closed taxonomy — never free text).",
            status=NodeStatus.NEEDS_REVIEW, severity=f.severity,
            confidence=o.confidence, reviewer_accuracy=o.reviewer_accuracy,
            source=o.source, parent_id=f.field_node_id, finding_ids=(f.id,),
            remediation=f.remediation,
            metadata={"reason": o.reason.value, "path": o.path},
        ))
        add_edge(f.field_node_id, f.id, EdgeRelation.AFFECTED_BY)
        add_edge(f.check_id, f.id, EdgeRelation.RAISED)
        refs = [o.source] + ([o.conflict_source] if o.conflict_source else [])
        for i, ref in enumerate(refs):
            eid = f"evidence:{f.id.split(':', 1)[1]}:{i}"
            span = ref.raw_span if ref.raw_span else "no span — field not found in this document"
            page = f"p.{ref.page}" if ref.page else "whole document"
            nodes.append(GraphNode(
                id=eid, analysis_id=analysis_id, category=NodeCategory.EVIDENCE,
                label=ref.doc_id, summary=f"{page} · “{span}”" if ref.raw_span else f"{page} · {span}",
                description=f"Verbatim source evidence in {ref.doc_id} ({ref.archetype}). "
                            "Spans render exactly as printed so format artifacts stay visible.",
                status=NodeStatus.INFO, severity=f.severity, source=ref, parent_id=f.id,
                finding_ids=(f.id,),
            ))
            add_edge(f.id, eid, EdgeRelation.EVIDENCED_BY)

    # ---- derived metrics (downstream components; Loop B — never a confidence) --------
    present: dict[FieldType, list[FieldOutcome]] = {}
    for o in outcomes:
        present.setdefault(o.field_type, []).append(o)
    for metric, inputs in METRIC_INPUTS.items():
        involved = [o for ft in inputs for o in present.get(ft, [])]
        if not involved:
            continue
        blocking = [finding_by_field[fid] for fid in (_field_node_id(o) for o in involved)
                    if fid in finding_by_field]
        missing = [ft.value for ft in inputs if ft not in present]
        blocked = bool(blocking) or bool(missing)
        mid = f"metric:{metric}"
        if blocked:
            why = (f"blocked by {len(blocking)} finding(s)" if blocking else "") + \
                  (" · " if blocking and missing else "") + \
                  (f"missing input: {', '.join(missing)}" if missing else "")
            m_summary = why
        else:
            m_summary = "inputs resolved — ready to compute (no coverage claim)"
        nodes.append(GraphNode(
            id=mid, analysis_id=analysis_id, category=NodeCategory.METRIC,
            label=metric, summary=m_summary,
            description=_METRIC_DESCRIPTION[metric] + (
                " This metric is currently blocked: at least one input field is routed, absent, "
                "or degraded, and Verdict refuses to compute on unreviewed inputs." if blocked
                else ""),
            status=NodeStatus.BLOCKED if blocked else NodeStatus.INFO, parent_id="file",
            metadata={"loop": "B", "guaranteed": False, "inputs": [ft.value for ft in inputs]},
        ))
        for o in involved:
            add_edge(_field_node_id(o), mid, EdgeRelation.FEEDS)
        for f in blocking:
            add_edge(f.id, mid, EdgeRelation.BLOCKS, propagates=True)

    # ---- recommended actions, consolidated by kind -----------------------------------
    action_defs = {
        "PATH_2": ("action:verify", "Verify extracted values",
                   "Check each routed value against its verbatim span; corrections feed the "
                   "calibrator."),
        "DEGRADED": ("action:verify", "Verify extracted values", ""),
        "PATH_1": ("action:source", "Locate or confirm absent fields",
                   "Find the field in the bundle or confirm it is genuinely not present."),
        "PATH_3": ("action:reconcile", "Reconcile conflicting sources",
                   "Decide which source is defensible and record the resolution."),
        "ERROR": ("action:rerun", "Resolve fault and re-run extraction",
                  "Fix the document fault, then re-run this bundle."),
    }
    made_actions: dict[str, str] = {}
    for f in findings:
        aid, label, desc = action_defs[f.outcome.path]
        if aid not in made_actions:
            made_actions[aid] = label
            nodes.append(GraphNode(
                id=aid, analysis_id=analysis_id, category=NodeCategory.ACTION,
                label=label, summary="recommended reviewer action",
                description=desc or action_defs["PATH_2"][2],
                status=NodeStatus.RECOMMENDED, parent_id="file",
            ))
        add_edge(f.id, aid, EdgeRelation.RESOLVED_BY)

    # ---- metadata --------------------------------------------------------------------
    counts: dict[str, int] = {"nodes": len(nodes), "edges": len(edges)}
    for n in nodes:
        counts[n.category.value] = counts.get(n.category.value, 0) + 1
    for f in findings:
        counts[f"severity:{f.severity.value}"] = counts.get(f"severity:{f.severity.value}", 0) + 1

    return MemoryGraph(
        metadata=GraphMetadata(
            analysis_id=analysis_id, file_label=file_label, generated_at=generated_at,
            status=status, worst_severity=overall, counts=counts,
        ),
        nodes=tuple(nodes),
        edges=tuple(edges),
    )
