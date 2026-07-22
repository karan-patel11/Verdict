"""Memory-graph validator — malformed graph data fails loudly at build time, never as a
detached edge in front of a reviewer.

The renderer downstream anchors every edge to measured node geometry; the only way it can
draw a broken graph is if the data lies. So the data is not allowed to lie: the experiment
calls `assert_valid` before a graph is persisted, and the front-end re-checks the same
invariants (dev-console warnings) before rendering a fetched report.
"""
from __future__ import annotations

from .schema import (
    CATEGORY_RANK,
    EdgeRelation,
    MemoryGraph,
    NodeCategory,
    Severity,
    severity_rank,
    worst_severity,
)

# The closed set of (source category, target category) each relation may connect.
RELATION_ENDPOINTS: dict[EdgeRelation, tuple[NodeCategory, NodeCategory]] = {
    EdgeRelation.SUMMARIZED_BY: (NodeCategory.FILE, NodeCategory.SUMMARY),
    EdgeRelation.CONTAINS: (NodeCategory.FILE, NodeCategory.DOCUMENT),
    EdgeRelation.EXTRACTED: (NodeCategory.DOCUMENT, NodeCategory.FIELD),
    EdgeRelation.CHECKED_BY: (NodeCategory.FIELD, NodeCategory.CHECK),
    EdgeRelation.RAISED: (NodeCategory.CHECK, NodeCategory.FINDING),
    EdgeRelation.AFFECTED_BY: (NodeCategory.FIELD, NodeCategory.FINDING),
    EdgeRelation.EVIDENCED_BY: (NodeCategory.FINDING, NodeCategory.EVIDENCE),
    EdgeRelation.FEEDS: (NodeCategory.FIELD, NodeCategory.METRIC),
    EdgeRelation.BLOCKS: (NodeCategory.FINDING, NodeCategory.METRIC),
    EdgeRelation.RESOLVED_BY: (NodeCategory.FINDING, NodeCategory.ACTION),
}


class GraphValidationError(ValueError):
    """Raised when a MemoryGraph violates the schema invariants; carries every problem found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid memory graph:\n  - " + "\n  - ".join(problems))


def validate_graph(graph: MemoryGraph) -> list[str]:
    """Return every invariant violation (empty list ⇒ valid)."""
    problems: list[str] = []
    ids: set[str] = set()
    for n in graph.nodes:
        if n.id in ids:
            problems.append(f"duplicate node id {n.id!r}")
        ids.add(n.id)
    by_id = graph.node_by_id()

    edge_ids: set[str] = set()
    incoming: dict[str, list[EdgeRelation]] = {}
    outgoing: dict[str, list[EdgeRelation]] = {}
    adjacency: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.id in edge_ids:
            problems.append(f"duplicate edge id {e.id!r}")
        edge_ids.add(e.id)
        src, dst = by_id.get(e.source), by_id.get(e.target)
        if src is None or dst is None:
            problems.append(f"edge {e.id!r} references missing node(s)")
            continue
        want = RELATION_ENDPOINTS[e.relation]
        if (src.category, dst.category) != want:
            problems.append(
                f"edge {e.id!r}: {e.relation.value} must connect "
                f"{want[0].value}→{want[1].value}, got {src.category.value}→{dst.category.value}"
            )
        if CATEGORY_RANK[dst.category] <= CATEGORY_RANK[src.category]:
            problems.append(f"edge {e.id!r} flows backward against the category hierarchy")
        if e.relation is EdgeRelation.BLOCKS and not e.propagates_issue:
            problems.append(f"edge {e.id!r}: BLOCKS edges must set propagates_issue")
        incoming.setdefault(e.target, []).append(e.relation)
        outgoing.setdefault(e.source, []).append(e.relation)
        adjacency.setdefault(e.source, []).append(e.target)

    # Required roots.
    files = [n for n in graph.nodes if n.category is NodeCategory.FILE]
    if len(files) != 1:
        problems.append(f"expected exactly one FILE root, found {len(files)}")
    if sum(1 for n in graph.nodes if n.category is NodeCategory.SUMMARY) != 1:
        problems.append("expected exactly one SUMMARY node")

    # Findings must be localized: affected field + raising check + verbatim evidence.
    for n in graph.nodes:
        if n.category is NodeCategory.FINDING:
            rels = incoming.get(n.id, [])
            if EdgeRelation.AFFECTED_BY not in rels:
                problems.append(f"finding {n.id!r} is not connected to an affected FIELD node")
            if EdgeRelation.RAISED not in rels:
                problems.append(f"finding {n.id!r} has no raising CHECK")
            if EdgeRelation.EVIDENCED_BY not in outgoing.get(n.id, []):
                problems.append(f"finding {n.id!r} has no EVIDENCE node")
            if severity_rank(n.severity) < severity_rank(Severity.LOW):
                problems.append(f"finding {n.id!r} must carry severity ≥ LOW")
            if not n.remediation:
                problems.append(f"finding {n.id!r} has no remediation guidance")

    # parent_id and finding_ids must resolve.
    for n in graph.nodes:
        if n.parent_id is not None and n.parent_id not in by_id:
            problems.append(f"node {n.id!r} has unresolved parent {n.parent_id!r}")
        for fid in n.finding_ids:
            ref = by_id.get(fid)
            if ref is None or ref.category is not NodeCategory.FINDING:
                problems.append(f"node {n.id!r} references non-finding {fid!r}")

    # No orphans: every node reachable from the file root along directed edges.
    if files:
        seen = {files[0].id}
        stack = [files[0].id]
        while stack:
            for nxt in adjacency.get(stack.pop(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        for n in graph.nodes:
            if n.id not in seen:
                problems.append(f"node {n.id!r} is unreachable from the FILE root")

    # Consolidated categories may not contain semantic duplicates.
    seen_labels: set[tuple[str, str]] = set()
    for n in graph.nodes:
        if n.category in (NodeCategory.CHECK, NodeCategory.METRIC, NodeCategory.ACTION):
            key = (n.category.value, n.label)
            if key in seen_labels:
                problems.append(f"duplicate {n.category.value} node for {n.label!r}")
            seen_labels.add(key)

    # Metadata must agree with the nodes it describes.
    md = graph.metadata
    finding_sevs = [n.severity for n in graph.nodes if n.category is NodeCategory.FINDING]
    if md.worst_severity is not worst_severity(finding_sevs):
        problems.append(
            f"metadata worst_severity {md.worst_severity.value} != derived "
            f"{worst_severity(finding_sevs).value}"
        )
    if md.counts.get("nodes") != len(graph.nodes) or md.counts.get("edges") != len(graph.edges):
        problems.append("metadata counts disagree with node/edge totals")
    return problems


def assert_valid(graph: MemoryGraph) -> MemoryGraph:
    problems = validate_graph(graph)
    if problems:
        raise GraphValidationError(problems)
    return graph
