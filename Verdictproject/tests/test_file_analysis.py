"""File-analysis records: the terminal timeline, terminal-state coverage, and the rule that
a graph is published only for analyses that actually finished."""
from __future__ import annotations

from pathlib import Path

import pytest

from abstention.experiment.report import build_report, embed_report
from abstention.memory import validate_graph
from abstention.memory.schema import (
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
)

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@pytest.fixture(scope="module")
def report():
    return build_report(CONFIGS / "shift_severe.yaml")


def test_analyses_cover_every_terminal_state(report):
    analyses = report["analyses"]
    assert len(analyses) >= 5
    statuses = {a["status"] for a in analyses}
    assert {"COMPLETED", "PARTIAL", "FAILED"} <= statuses


def test_graph_published_only_for_finished_analyses(report):
    for a in report["analyses"]:
        if a["status"] == "FAILED":
            assert a["graph"] is None and a["error"] is not None
            assert any(e["kind"] == "error" for e in a["events"])
        else:
            assert a["graph"] is not None
            g = a["graph"]
            assert g["metadata"]["analysis_id"] == a["analysis_id"]
            assert g["metadata"]["schema_version"] == "memory-graph/1"
            # Round-trip the serialized graph through the validator: what the front-end
            # receives must satisfy the same invariants the builder promised.
            assert validate_graph(_from_dict(g)) == []


def test_events_are_ordered_and_stage_monotonic(report):
    stage_order = {s: i for i, s in enumerate(
        ("QUEUE", "LOAD", "EXTRACT", "SCORE", "DECIDE", "RECONCILE", "DERIVE", "GRAPH", "DONE"))}
    for a in report["analyses"]:
        seqs = [e["seq"] for e in a["events"]]
        assert seqs == list(range(len(seqs)))
        stages = [stage_order[e["stage"]] for e in a["events"]]
        assert stages == sorted(stages)
        assert a["events"][-1]["stage"] == "DONE"


def test_terminal_findings_match_graph_findings(report):
    for a in report["analyses"]:
        if a["graph"] is None:
            continue
        graph_findings = {n["id"] for n in a["graph"]["nodes"] if n["category"] == "FINDING"}
        listed = {f["id"] for f in a["findings"]}
        event_refs = {e["finding_id"] for e in a["events"] if "finding_id" in e}
        assert listed == graph_findings
        assert event_refs == graph_findings


def test_paths_exercised_across_showcases(report):
    reasons = {f["reason"] for a in report["analyses"] for f in a["findings"]}
    # Under shift_severe the binding Loop-A clause is usually the reviewer-accuracy gate;
    # either PATH_2 route reason is a faithful mirror of the loop's rule.
    assert reasons & {"CONFORMITY_SCORE_ABOVE_THRESHOLD",
                      "CALIBRATED_CONFIDENCE_BELOW_REVIEWER_ACCURACY"}
    assert "FIELD_ABSENT_FROM_DOCUMENT" in reasons
    assert "CROSS_DOCUMENT_VALUE_CONFLICT" in reasons
    assert "NO_CONFIDENCE_AVAILABLE" in reasons


def test_severity_semantics_in_report(report):
    for a in report["analyses"]:
        for f in a["findings"]:
            if f["reason"] == "CROSS_DOCUMENT_VALUE_CONFLICT":
                assert f["severity"] == "HIGH"
            if f["reason"] == "CONFORMITY_SCORE_ABOVE_THRESHOLD":
                assert f["severity"] == "LOW"


def test_analyses_are_deterministic():
    a = build_report(CONFIGS / "shift_severe.yaml")["analyses"]
    b = build_report(CONFIGS / "shift_severe.yaml")["analyses"]
    for x, y in zip(a, b):
        x = {k: v for k, v in x.items() if k != "graph"} | {"g": _strip_time(x["graph"])}
        y = {k: v for k, v in y.items() if k != "graph"} | {"g": _strip_time(y["graph"])}
        assert x == y


def test_embed_report_is_idempotent(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<html><body><script type="application/json" id="report">OLD</script>'
                    "<script>1</script></body></html>")
    assert embed_report({"k": "</script>"}, page) is True
    once = page.read_text()
    assert "OLD" not in once and "<\\/script>" in once
    assert embed_report({"k": "</script>"}, page) is True
    assert page.read_text() == once
    plain = tmp_path / "no-marker.html"
    plain.write_text("<html></html>")
    assert embed_report({}, plain) is False


def _strip_time(g):
    if g is None:
        return None
    md = dict(g["metadata"])
    md.pop("generated_at", None)
    return {**g, "metadata": md}


def _from_dict(g: dict) -> MemoryGraph:
    """Rehydrate a serialized graph for validator round-trip checks."""
    nodes = tuple(
        GraphNode(
            id=n["id"], analysis_id=n["analysis_id"], category=NodeCategory(n["category"]),
            label=n["label"], summary=n["summary"], description=n["description"],
            status=NodeStatus(n["status"]), severity=Severity(n["severity"]),
            confidence=n["confidence"], reviewer_accuracy=n["reviewer_accuracy"],
            source=SourceRef(doc_id=n["source"]["doc_id"], archetype=n["source"]["archetype"],
                             page=n["source"]["page"],
                             bbox=tuple(n["source"]["bbox"]) if n["source"]["bbox"] else None,
                             raw_span=n["source"]["raw_span"]) if n["source"] else None,
            finding_ids=tuple(n["finding_ids"]), parent_id=n["parent_id"],
            remediation=n["remediation"], metadata=n["metadata"],
        )
        for n in g["nodes"]
    )
    edges = tuple(
        GraphEdge(id=e["id"], source=e["source"], target=e["target"],
                  relation=EdgeRelation(e["relation"]),
                  propagates_issue=e["propagates_issue"], weight=e["weight"])
        for e in g["edges"]
    )
    md = g["metadata"]
    return MemoryGraph(
        metadata=GraphMetadata(
            analysis_id=md["analysis_id"], file_label=md["file_label"],
            schema_version=md["schema_version"], generated_at=md["generated_at"],
            status=AnalysisStatus(md["status"]), worst_severity=Severity(md["worst_severity"]),
            counts=md["counts"],
        ),
        nodes=nodes, edges=edges,
    )
