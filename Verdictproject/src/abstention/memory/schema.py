"""Memory-graph schema — the typed contract between analysis and rendering.

One MemoryGraph is generated per analyzed credit file when (and only when) that file's
analysis reaches a terminal state. The category system, edge relations, and column ranks are
FIXED across files: file-specific content changes the node payloads, counts, and issue
states, never the shape of the schema. That stability is what lets a reviewer read the third
graph as fast as the first.

Design rules carried from the rest of the project:

- Closed enums, never free text (invariant 12) — categories, relations, severities, statuses.
- Findings must point at the exact affected node and at verbatim evidence (invariant 9);
  a detached red node is a validation error, not a style choice.
- No fabricated numbers: derived metrics carry NO propagated confidence (propagation is
  unsolved — derived/propagation.py); a metric downstream of a routed field is BLOCKED,
  not "low confidence."
- Domain data only: node positions are a layout concern and never appear here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

GRAPH_SCHEMA_VERSION = "memory-graph/1"


class NodeCategory(StrEnum):
    FILE = "FILE"  # the analyzed credit file (root)
    SUMMARY = "SUMMARY"  # analysis summary
    DOCUMENT = "DOCUMENT"  # a source document in the bundle (structural area)
    FIELD = "FIELD"  # an extracted field entity
    CHECK = "CHECK"  # a rule actually exercised (threshold, absence, reconciliation…)
    FINDING = "FINDING"  # an issue localized to a field
    EVIDENCE = "EVIDENCE"  # verbatim source evidence for a finding
    METRIC = "METRIC"  # a derived credit metric (downstream component)
    ACTION = "ACTION"  # recommended reviewer action


# Canonical left-to-right column per category. Shared with the front-end layout engine so the
# hierarchy reads identically for every file; tested on both sides.
CATEGORY_RANK: Mapping[NodeCategory, int] = MappingProxyType(
    {
        NodeCategory.FILE: 0,
        NodeCategory.SUMMARY: 1,
        NodeCategory.DOCUMENT: 1,
        NodeCategory.FIELD: 2,
        NodeCategory.CHECK: 3,
        NodeCategory.FINDING: 4,
        NodeCategory.EVIDENCE: 5,
        NodeCategory.METRIC: 6,
        NodeCategory.ACTION: 7,
    }
)


class NodeStatus(StrEnum):
    INFO = "INFO"  # structural / informational
    VALIDATED = "VALIDATED"  # accepted under the guaranteed threshold
    NEEDS_REVIEW = "NEEDS_REVIEW"  # routed to a human
    BLOCKED = "BLOCKED"  # derived metric waiting on a routed/absent input
    FAILED = "FAILED"  # extraction or analysis fault
    RECOMMENDED = "RECOMMENDED"  # agent-recommended action


class Severity(StrEnum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_SEVERITY_ORDER: Mapping[Severity, int] = MappingProxyType(
    {Severity.NONE: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}
)


def severity_rank(sev: Severity) -> int:
    return _SEVERITY_ORDER[sev]


def worst_severity(severities: list[Severity]) -> Severity:
    worst = Severity.NONE
    for s in severities:
        if severity_rank(s) > severity_rank(worst):
            worst = s
    return worst


class EdgeRelation(StrEnum):
    """Directed relations; every edge flows toward a strictly higher category rank except
    where noted, so the rendered graph is a layered DAG with no accidental back-edges."""

    SUMMARIZED_BY = "SUMMARIZED_BY"  # file → summary
    CONTAINS = "CONTAINS"  # file → document
    EXTRACTED = "EXTRACTED"  # document → field
    CHECKED_BY = "CHECKED_BY"  # field → check
    RAISED = "RAISED"  # check → finding
    AFFECTED_BY = "AFFECTED_BY"  # field → finding (the localization edge)
    EVIDENCED_BY = "EVIDENCED_BY"  # finding → evidence
    FEEDS = "FEEDS"  # field → metric (deterministic dependency)
    BLOCKS = "BLOCKS"  # finding → metric (issue propagation)
    RESOLVED_BY = "RESOLVED_BY"  # finding → action


EDGE_LABEL: Mapping[EdgeRelation, str] = MappingProxyType(
    {
        EdgeRelation.SUMMARIZED_BY: "summarized by",
        EdgeRelation.CONTAINS: "contains",
        EdgeRelation.EXTRACTED: "extracted",
        EdgeRelation.CHECKED_BY: "checked by",
        EdgeRelation.RAISED: "raised",
        EdgeRelation.AFFECTED_BY: "affected by",
        EdgeRelation.EVIDENCED_BY: "evidenced by",
        EdgeRelation.FEEDS: "feeds",
        EdgeRelation.BLOCKS: "blocks",
        EdgeRelation.RESOLVED_BY: "resolved by",
    }
)


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"  # every field reached a decision
    PARTIAL = "PARTIAL"  # completed with absent/degraded fields flagged
    FAILED = "FAILED"  # aborted; no graph is published


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Verbatim provenance — same contract as domain.models.Provenance, tolerant of the
    absent-field case where page/bbox/span legitimately do not exist."""

    doc_id: str
    archetype: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    raw_span: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "archetype": self.archetype,
            "page": self.page,
            "bbox": list(self.bbox) if self.bbox else None,
            "raw_span": self.raw_span,
        }


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    analysis_id: str
    category: NodeCategory
    label: str
    summary: str  # one line, shown on the node / hover
    description: str = ""  # full text for the details panel
    status: NodeStatus = NodeStatus.INFO
    severity: Severity = Severity.NONE
    confidence: float | None = None  # raw extractor softmax where one exists (calibrator off-path)
    reviewer_accuracy: float | None = None  # the accuracy the confidence was compared to
    source: SourceRef | None = None
    finding_ids: tuple[str, ...] = ()  # findings this node participates in
    parent_id: str | None = None  # grouping parent (file for documents, document for fields…)
    remediation: str | None = None  # findings only
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "category": self.category.value,
            "rank": CATEGORY_RANK[self.category],
            "label": self.label,
            "summary": self.summary,
            "description": self.description,
            "status": self.status.value,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "reviewer_accuracy": self.reviewer_accuracy,
            "source": self.source.to_dict() if self.source else None,
            "finding_ids": list(self.finding_ids),
            "parent_id": self.parent_id,
            "remediation": self.remediation,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    source: str
    target: str
    relation: EdgeRelation
    propagates_issue: bool = False  # BLOCKS edges: the issue travels downstream
    weight: float | None = None  # confidence where meaningful; never fabricated

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation.value,
            "label": EDGE_LABEL[self.relation],
            "propagates_issue": self.propagates_issue,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class GraphMetadata:
    analysis_id: str
    file_label: str
    schema_version: str = GRAPH_SCHEMA_VERSION
    generated_at: str = ""  # ISO timestamp of the report build (real, recorded once)
    status: AnalysisStatus = AnalysisStatus.COMPLETED
    worst_severity: Severity = Severity.NONE
    counts: Mapping[str, int] = field(default_factory=dict)  # by category and by severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "file_label": self.file_label,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "status": self.status.value,
            "worst_severity": self.worst_severity.value,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True, slots=True)
class MemoryGraph:
    metadata: GraphMetadata
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def node_by_id(self) -> dict[str, GraphNode]:
        return {n.id: n for n in self.nodes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
