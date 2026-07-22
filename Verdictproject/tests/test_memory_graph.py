"""Memory-graph schema, builder, and validator invariants.

The graph is a product surface: a detached edge or an orphaned finding in front of a
reviewer is a legibility failure, so every one of those failure modes is a hard error here.
"""
from __future__ import annotations

import pytest

from abstention.domain.taxonomy import AcceptReason, RouteReason
from abstention.domain.types import FieldType
from abstention.memory import (
    AnalysisStatus,
    CATEGORY_RANK,
    EdgeRelation,
    FieldOutcome,
    GraphEdge,
    GraphValidationError,
    MemoryGraph,
    NodeCategory,
    NodeStatus,
    Severity,
    SourceRef,
    assert_valid,
    build_file_graph,
    derive_findings,
    validate_graph,
)


def _ref(doc="balance_shee-1001", page=2, span="$1,234.00"):
    return SourceRef(doc_id=doc, archetype="BALANCE_SHEET", page=page,
                     bbox=(0.1, 0.2, 0.22, 0.23), raw_span=span)


def _outcomes():
    """A representative bundle: two accepts, one uncertain route, one absent, one conflict,
    one degraded — every path the taxonomy defines."""
    return [
        FieldOutcome(index=0, field_type=FieldType.NET_INCOME, path="PATH_2",
                     decision="ACCEPT", reason=AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD,
                     source=_ref(), confidence=0.93, reviewer_accuracy=0.7, ood_score=0.1,
                     tau=0.25),
        FieldOutcome(index=1, field_type=FieldType.DEPRECIATION, path="PATH_2",
                     decision="ACCEPT", reason=AcceptReason.CONFORMITY_SCORE_WITHIN_THRESHOLD,
                     source=_ref(span="88,120"), confidence=0.91, reviewer_accuracy=0.7,
                     ood_score=0.1, tau=0.25),
        FieldOutcome(index=2, field_type=FieldType.TOTAL_DEBT_SERVICE, path="PATH_2",
                     decision="ROUTE", reason=RouteReason.CONFORMITY_SCORE_ABOVE_THRESHOLD,
                     source=_ref(doc="bank_stateme-2002", span="410833"), confidence=0.61,
                     reviewer_accuracy=0.7, ood_score=0.4, tau=0.25),
        FieldOutcome(index=3, field_type=FieldType.GROSS_REVENUE, path="PATH_1",
                     decision="ROUTE", reason=RouteReason.FIELD_ABSENT_FROM_DOCUMENT,
                     source=SourceRef(doc_id="multi_docume-3003",
                                      archetype="MULTI_DOCUMENT_DERIVED"), tau=0.25),
        FieldOutcome(index=4, field_type=FieldType.COGS, path="PATH_3", decision="ROUTE",
                     reason=RouteReason.CROSS_DOCUMENT_VALUE_CONFLICT,
                     source=_ref(span="575350"), confidence=0.89, reviewer_accuracy=0.7,
                     ood_score=0.2, tau=0.25,
                     conflict_source=_ref(doc="profit_and_l-4004", span="$3,839,829.00")),
        FieldOutcome(index=5, field_type=FieldType.NSF_COUNT, path="DEGRADED",
                     decision="ROUTE", reason=RouteReason.NO_CONFIDENCE_AVAILABLE,
                     source=_ref(doc="bank_stateme-2002", span="4"), ood_score=0.3, tau=0.25),
    ]


def _graph(outcomes=None, status=AnalysisStatus.COMPLETED):
    return build_file_graph(analysis_id="an-case-00001", file_label="case-00001.bundle",
                            outcomes=outcomes if outcomes is not None else _outcomes(),
                            status=status, generated_at="2026-07-17T00:00:00+00:00")


def test_builder_output_is_valid():
    assert validate_graph(_graph()) == []


def test_findings_derive_only_from_routed_fields_with_fixed_severity():
    findings = derive_findings(_outcomes())
    assert len(findings) == 4  # 2 accepts produce no finding
    by_path = {f.outcome.path: f for f in findings}
    assert by_path["PATH_2"].severity is Severity.LOW
    assert by_path["PATH_1"].severity is Severity.MEDIUM
    assert by_path["DEGRADED"].severity is Severity.MEDIUM
    assert by_path["PATH_3"].severity is Severity.HIGH
    assert all(f.remediation for f in findings)


def test_every_finding_connects_to_affected_field_check_and_evidence():
    g = _graph()
    edges_in: dict[str, set[EdgeRelation]] = {}
    edges_out: dict[str, set[EdgeRelation]] = {}
    for e in g.edges:
        edges_in.setdefault(e.target, set()).add(e.relation)
        edges_out.setdefault(e.source, set()).add(e.relation)
    findings = [n for n in g.nodes if n.category is NodeCategory.FINDING]
    assert findings
    for f in findings:
        assert EdgeRelation.AFFECTED_BY in edges_in[f.id]
        assert EdgeRelation.RAISED in edges_in[f.id]
        assert EdgeRelation.EVIDENCED_BY in edges_out[f.id]


def test_contradiction_carries_both_sources_as_evidence():
    g = _graph()
    conflict = next(n for n in g.nodes if n.category is NodeCategory.FINDING
                    and n.metadata.get("path") == "PATH_3")
    evidence = [e.target for e in g.edges
                if e.source == conflict.id and e.relation is EdgeRelation.EVIDENCED_BY]
    assert len(evidence) == 2


def test_blocked_metric_has_propagation_edges_and_no_confidence():
    g = _graph()
    dscr = next(n for n in g.nodes if n.id == "metric:DSCR")
    # TOTAL_DEBT_SERVICE routed ⇒ DSCR must be blocked, and must never carry a confidence.
    assert dscr.status is NodeStatus.BLOCKED
    assert dscr.confidence is None
    blocks = [e for e in g.edges if e.target == dscr.id and e.relation is EdgeRelation.BLOCKS]
    assert blocks and all(e.propagates_issue for e in blocks)
    feeds = [e for e in g.edges if e.target == dscr.id and e.relation is EdgeRelation.FEEDS]
    assert len(feeds) == 3  # all three DSCR inputs are present in the bundle


def test_identical_input_produces_identical_graph():
    assert _graph().to_dict() == _graph().to_dict()


def test_single_field_bundle_builds_minimal_valid_graph():
    g = _graph(outcomes=_outcomes()[:1])
    assert validate_graph(g) == []
    cats = {n.category for n in g.nodes}
    assert NodeCategory.FILE in cats and NodeCategory.SUMMARY in cats
    assert not any(n.category is NodeCategory.FINDING for n in g.nodes)
    assert g.metadata.worst_severity is Severity.NONE


def test_category_ranks_are_strictly_forward_for_all_edges():
    g = _graph()
    by_id = g.node_by_id()
    for e in g.edges:
        assert CATEGORY_RANK[by_id[e.target].category] > CATEGORY_RANK[by_id[e.source].category]


def test_validator_rejects_dangling_edge_and_duplicate_id():
    g = _graph()
    bad = MemoryGraph(metadata=g.metadata, nodes=g.nodes,
                      edges=g.edges + (GraphEdge(id="x", source="file", target="ghost",
                                                 relation=EdgeRelation.CONTAINS),))
    problems = validate_graph(bad)
    assert any("missing node" in p for p in problems)

    dup = MemoryGraph(metadata=g.metadata, nodes=g.nodes + (g.nodes[-1],), edges=g.edges)
    assert any("duplicate node id" in p for p in validate_graph(dup))

    with pytest.raises(GraphValidationError):
        assert_valid(bad)


def test_validator_rejects_detached_finding():
    g = _graph()
    pruned = MemoryGraph(
        metadata=g.metadata, nodes=g.nodes,
        edges=tuple(e for e in g.edges if e.relation is not EdgeRelation.AFFECTED_BY),
    )
    assert any("not connected to an affected FIELD" in p for p in validate_graph(pruned))


def test_validator_rejects_metadata_drift():
    g = _graph()
    lied = MemoryGraph(
        metadata=type(g.metadata)(
            analysis_id=g.metadata.analysis_id, file_label=g.metadata.file_label,
            generated_at=g.metadata.generated_at, status=g.metadata.status,
            worst_severity=Severity.NONE, counts=dict(g.metadata.counts),
        ),
        nodes=g.nodes, edges=g.edges,
    )
    assert any("worst_severity" in p for p in validate_graph(lied))
